# -*- coding: utf-8 -*-
from ctypes import *
import platform

arch = platform.architecture()[0]
if arch in ('64bit'): # ('32bit', '64bit')
    piapi = windll.piapi
elif arch == '32bit':
    piapi = windll.piapi32

connected = True
piserver = create_string_buffer(b"PI-SERVER-1") # Servidor do PI
username = create_string_buffer(b"pidemo")      # Usuário di PI
passwrd = create_string_buffer(b"")             # Senha do usuário do PI
valid = c_int(0)

setservernode = piapi.piut_setservernode(pointer(piserver))
result = piapi.piut_login(pointer(username), pointer(passwrd), pointer(valid))


def pitm_parsetime(piapi, timestr):
    timedate = c_int()
    stat = piapi.pitm_parsetime(timestr, 1, pointer(timedate))
    if stat != 0:
        print
        print("Error parsing time: %s" % (timestr))
        print
        return None
    else:
        return timedate


def pipt_findpoint(piapi, tagname):
    pointid = c_int()
    stat = piapi.pipt_findpoint(tagname, pointer(pointid))
    if stat != 0:
        print
        print("Error %d in findpoint for %s" % (stat, tagname))
        print
        return None
    else:
        return pointid


t = bytes("3-Jun-26 19:33:00", "utf-8")
#t = bytes("t", "utf-8")

pitime = pitm_parsetime(piapi, t)

print('pitime:', pitime)

tag = "sinusoid"

tag = bytes(tag, "utf-8")

pointid = pipt_findpoint(piapi, tag)

print('pointid:', pointid)

mode = c_int(3)
rval = c_float()
istats = c_int()

stat = piapi.piar_value(
    pointid, pointer(pitime), mode, pointer(rval), pointer(istats))

print('stat:', stat)
print('rval:', rval.value)
