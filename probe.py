#!/usr/bin/env python
import argparse
import sys
import socket
import random
import struct

from scapy.all import sendp, send, get_if_list, get_if_hwaddr, bind_layers
from scapy.all import Packet, BitField, Raw
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

class Hula(Packet):
    fields_desc = [ BitField("dst_tor", 0, 24),
                   BitField("path_util", 0, 8)]

bind_layers(IP, Hula, proto=0x42)

def main():

    iface = get_if()

    print "sending probe on interface %s." % (iface)
    pkt =  Ether(src=get_if_hwaddr(iface), dst='ff:ff:ff:ff:ff:ff')
    pkt = pkt / IP(dst="224.0.0.1", proto=66)
    pkt = pkt / Hula(dst_tor=0, path_util=256)
    pkt = pkt / Raw("probe packet")
    pkt.show2()
    sendp(pkt, iface=iface, verbose=False)


if __name__ == '__main__':
    main()
