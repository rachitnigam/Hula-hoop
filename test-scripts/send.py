#!/usr/bin/env python
import argparse
import sys
import time
import socket
import random
import struct

from scapy.all import sendp, send, get_if_list, get_if_hwaddr
from scapy.all import Packet
from scapy.all import Ether, IP, UDP, TCP

def get_if():
    ifs=get_if_list()
    iface=None # "h1-eth0"
    for i in get_if_list():
        if "eth0" in i:
            iface=i
            break;
    if not iface:
        print "Cannot find eth0 interface"
        exit(1)
    return iface

def create_packet(addr, iface, load):
    pkt =  Ether(src=get_if_hwaddr(iface), dst='ff:ff:ff:ff:ff:ff')
    pkt = pkt /IP(dst=addr) / TCP(dport=1234, sport=58264) / load
    pkt.show2()

    return pkt

def main():

    count = 1

    if len(sys.argv)<3:
        print 'pass 2 arguments: <destination> "<message>"'
        exit(1)

    if len(sys.argv) == 4:
        count = int(sys.argv[3])

    addr = socket.gethostbyname(sys.argv[1])
    iface = get_if()

    print "sending on interface %s to %s" % (iface, str(addr))

    # The check is intentially in place to allow for infinite loops
    while count != 0:
        pkt = create_packet(addr, iface, sys.argv[2] + str(count))
        sendp(pkt, iface=iface, verbose=False)
        count -= 1
        time.sleep(0.5)


if __name__ == '__main__':
    main()
