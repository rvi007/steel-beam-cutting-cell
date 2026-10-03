"""
YOUR ROBOT PROGRAM - edit this file, save, then run:

    python3 my_program.py

Commands:
    bot.move_joints([j1, j2, j3, j4, j5, j6])   all 6 joints, in degrees
    bot.move_joint(number, angle)               one joint (1..6)
    bot.home()                                  back to the start pose
    bot.wait(seconds)                           pause
    bot.tool_position()                         returns [x, y, z] in metres
    bot.speed = 30                              slower (degrees per second)

The orange dotted line shows the path the tool tip travelled.
"""
from sim import Robot

bot = Robot()

# --- Example: wave hello ---
bot.move_joints([0, -90, 45, -90, 0, 0])   # bend the elbow
for _ in range(2):
    bot.move_joint(4, -45)                 # wrist up
    bot.move_joint(4, -135)                # wrist down

# --- Example: reach forward, then swing to the side ---
bot.move_joints([0, -45, 90, -135, -90, 0])
print("Tool is at:", bot.tool_position())
bot.move_joint(1, 90)                      # rotate the base 90°

bot.home()

# ============================================================
# YOUR TURN - write your own moves below this line.
# Exercise 1: Rotate the base to -90° and back to 0°.
# Exercise 2: Make the arm point straight forward (hint: J2 = 0).
# Exercise 3: Find a pose where the tool's Z is below 0.2 m.
# ============================================================


bot.done()
