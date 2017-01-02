#!/usr/bin/python
# pwd2pash.py - create password_hash as used in http.api_users.password_hash configs

import binascii
import hashlib
import getpass
import os

plain_passwd = getpass.getpass("Enter plain password: ")
the_salt = b'\x02O\xc0P?\x16\xc4\xdb\xbe\x96\xba\xb4\xa9r\x87\xe0'  # os.urandom(16)
iterations = 100000
dk = hashlib.pbkdf2_hmac('sha256', plain_passwd.encode('utf-8'), the_salt, iterations)
print(binascii.hexlify(dk))

