"""
MODEL ANSWERS for exercises.py - try each exercise yourself first!

Watch one:   python3 exercises.py 5 --solution
"""


def ex1(bot):
    """BASE SPIN"""
    bot.move_joint(1, -90)
    bot.move_joint(1, 90)
    bot.move_joint(1, 0)


def ex2(bot):
    """REACH FAR"""
    # J2 = 0 lays the upper arm flat; J3 = 0 keeps the forearm in line with it.
    bot.move_joints([0, 0, 0, -90, -90, 0])


def ex3(bot):
    """LOW BUT SAFE"""
    bot.move_joints([0, -45, 90, -135, -90, 0])  # Z is about 0.03 m


def ex4(bot):
    """HIT THE TARGET"""
    bot.move_joints([30, -80, 110, -120, -90, 0])


def ex5(bot):
    """LIGHTHOUSE SWEEP"""
    bot.move_joints([-180, -45, 90, -135, -90, 0])  # reach out, base at -180
    bot.move_joint(1, 180, speed=90)                # one full turn


def ex6(bot):
    """SPIN THE TOOL, NOT THE TIP"""
    # J6 spins around the tool's own axis, so the tip stays put.
    bot.move_joints([0, -45, 90, -135, -90, 0])
    bot.move_joint(6, 180)


def ex7(bot):
    """CLOCK FACE"""
    bot.move_joints([0, -45, 90, -135, -90, 0])
    for angle in range(-180, 180, 30):
        bot.move_joint(1, angle)


def ex8(bot):
    """PICK AND PLACE"""
    pick = [45, -60, 100, -130, -90, 0]
    above = [45, -90, 90, -90, -90, 0]  # same base angle, lifted to Z ~0.43 m

    bot.move_joints(above)
    bot.move_joints(pick)               # down to A
    bot.move_joints(above)              # lift
    bot.move_joint(1, -45)              # swing over B (mirror of A)
    bot.move_joints([-45] + pick[1:])   # down to B
    bot.move_joint(2, -90)              # lift off
    bot.home()
