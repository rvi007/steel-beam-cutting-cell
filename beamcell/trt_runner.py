"""
Run a YOLO model on the Jetson's GPU with TensorRT.

A TensorRT "engine" (models/*.engine) is the model compiled for THIS GPU - it is built once on
the Jetson from the .onnx file (tools/make_trt_engine.sh, about 5-10 minutes) and then loads in
a second. On the Orin Nano it runs YOLO roughly ten times faster than the CPU and leaves the CPU
free for planning and safety.

Nothing extra to install: TensorRT and CUDA come with JetPack. The GPU memory is handled through
the CUDA runtime library (libcudart) with Python's built-in ctypes, so neither PyTorch nor pycuda
is needed.
"""
import ctypes
import glob
import os

import numpy as np

H2D, D2H = 1, 2                       # cudaMemcpyHostToDevice, cudaMemcpyDeviceToHost


def _cudart():
    names = ["libcudart.so"] + sorted(glob.glob("/usr/local/cuda*/lib64/libcudart.so*"), reverse=True) + \
            sorted(glob.glob("/usr/lib/aarch64-linux-gnu/libcudart.so*"), reverse=True)
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    raise RuntimeError("the CUDA runtime (libcudart) isn't found - is JetPack installed?")


def available():
    """(True, version) if TensorRT and CUDA can be used here, else (False, why)."""
    try:
        import tensorrt as trt
    except ImportError:
        return False, "TensorRT for Python isn't installed (on the Jetson: sudo apt install python3-libnvinfer)"
    try:
        _cudart()
    except RuntimeError as e:
        return False, str(e)
    return True, trt.__version__


class TrtRunner:
    """One engine, one image at a time: infer(blob) -> the model's first output as a numpy array."""

    def __init__(self, path, size=640):
        import tensorrt as trt
        self.cuda = _cudart()
        logger = trt.Logger(trt.Logger.WARNING)
        with open(path, "rb") as fh:
            self.engine = trt.Runtime(logger).deserialize_cuda_engine(fh.read())
        if self.engine is None:
            raise RuntimeError(f"{os.path.basename(path)} wasn't built for this TensorRT / GPU - build it again on this Jetson")
        self.ctx = self.engine.create_execution_context()
        self.stream = ctypes.c_void_p()
        self._check(self.cuda.cudaStreamCreate(ctypes.byref(self.stream)), "cudaStreamCreate")
        self.inputs, self.outputs, self._dev = [], [], []
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            is_input = self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
            shape = list(self.engine.get_tensor_shape(name))
            if is_input and -1 in shape:              # dynamic model: one image, size x size
                shape = [1, 3, size, size]
                self.ctx.set_input_shape(name, shape)
            dtype = np.dtype(trt.nptype(self.engine.get_tensor_dtype(name)))
            (self.inputs if is_input else self.outputs).append([name, shape, dtype])
        for t in self.outputs:                        # output sizes are known once the input shape is set
            t[1] = list(self.ctx.get_tensor_shape(t[0]))
        for name, shape, dtype in self.inputs + self.outputs:
            ptr = ctypes.c_void_p()
            nbytes = int(np.prod(shape)) * dtype.itemsize
            self._check(self.cuda.cudaMalloc(ctypes.byref(ptr), ctypes.c_size_t(nbytes)), "cudaMalloc")
            self._dev.append(ptr)
            self.ctx.set_tensor_address(name, ptr.value)
        self.size = self.inputs[0][1][-1]
        self._host_out = [np.empty(shape, dtype) for _, shape, dtype in self.outputs]

    def _check(self, err, what):
        if err != 0:
            raise RuntimeError(f"{what} failed (CUDA error {err})")

    def infer(self, blob):
        name, shape, dtype = self.inputs[0]
        x = np.ascontiguousarray(blob, dtype=dtype).reshape(shape)
        self._check(self.cuda.cudaMemcpyAsync(self._dev[0], ctypes.c_void_p(x.ctypes.data), ctypes.c_size_t(x.nbytes),
                                              H2D, self.stream), "copy to GPU")
        if not self.ctx.execute_async_v3(self.stream.value):
            raise RuntimeError("TensorRT inference failed")
        n_in = len(self.inputs)
        for k, out in enumerate(self._host_out):
            self._check(self.cuda.cudaMemcpyAsync(ctypes.c_void_p(out.ctypes.data), self._dev[n_in + k],
                                                  ctypes.c_size_t(out.nbytes), D2H, self.stream), "copy from GPU")
        self._check(self.cuda.cudaStreamSynchronize(self.stream), "cudaStreamSynchronize")
        return self._host_out[0]

    def close(self):
        for ptr in self._dev:
            self.cuda.cudaFree(ptr)
        self._dev = []
        if self.stream:
            self.cuda.cudaStreamDestroy(self.stream)
            self.stream = None

    def __del__(self):
        try:
            self.close()
        except Exception:                                 # noqa: BLE001 - shutting down
            pass
