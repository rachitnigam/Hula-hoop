#!/usr/bin/env python2
import argparse, re, grpc, os, sys, json, subprocess
import networkx as nx

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utils/'))
import p4runtime_lib.helper

from p4runtime_lib.switch import ShutdownAllSwitchConnections
from p4runtime_lib.convert import decodeMac, decodeIPv4
from switch_utils import printGrpcError,load_topology,run_ssc_cmd

# Turn on dry run mode
debug = False

# Generate a simple UID for dst_id of each host
def host_to_dst_id(hosts):
    return dict(zip(hosts, range(1, len(hosts) + 1)))

def mcast_grp_command(mcast_id, port_ids, handle_id):
    port_seq = " ".join(str(e) for e in port_ids)
    create = "mc_mgrp_create " + str(mcast_id)
    node = "mc_node_create 0 " + port_seq
    assoc = "mc_node_associate " + str(mcast_id) + " " + str(handle_id)
    return create + "\n" + node + "\n" + assoc

def install_smart_mcast(mn_topo, switches, p4info_helper):
    # Note(rachit): Hosts are always considered downstream.
    def is_upstream(x, y):
        return x[0] == y[0] and int(x[1]) < int(y[1])

    G = nx.Graph()
    G.add_edges_from(mn_topo.links())
    # Generate mcast commands and store them in config/<switch>
    for switch in mn_topo.switches():
        command = ""
        adjacents = map(lambda (_, a): a, G.edges(switch))
        for adj in adjacents:
            mcast_adjs = None
            # If the packet came from an upstream link, cast it to only downstream links
            if is_upstream(switch, adj):
                mcast_adjs = filter(lambda a: not is_upstream(switch, a), adjacents)
            # If the packet came from a downstream link, cast it at all other links.
            else:
                mcast_adjs = filter(lambda a: a != adj, adjacents)

            mcast_ports = map(lambda a: mn_topo.port(switch, a)[0], mcast_adjs)
            ingress_port = mn_topo.port(switch, adj)[0]
            cmd = mcast_grp_command(ingress_port, mcast_ports,
                                    switches[switch].getAndUpdateHandleId())
            command += (cmd + "\n")
        # Execute mcast setup
        print run_ssc_cmd(switch, command)

def install_hula_logic(mn_topo, switches, p4info_helper):
    for sw in mn_topo.switches():
        add_hula_handle_probe = p4info_helper.buildTableEntry(
            table_name="MyIngress.hula_logic",
            match_fields = {
                "hdr.ipv4.protocol": 0x42
            },
            action_name = "MyIngress.hula_handle_probe",
            action_params = {
        })
        add_hula_handle_data_packet = p4info_helper.buildTableEntry(
            table_name="MyIngress.hula_logic",
            match_fields = {
                "hdr.ipv4.protocol": 0x06
            },
            action_name = "MyIngress.hula_handle_data_packet",
            action_params = {
        })
        switches[sw].WriteTableEntry(add_hula_handle_probe, debug)
        switches[sw].WriteTableEntry(add_hula_handle_data_packet, debug)

def install_tables(mn_topo, switches, p4info_helper):
    # Install entries for hula_logic
    install_hula_logic(mn_topo, switches, p4info_helper)
    # Install rule to map each host to dst_tor
    for (x, y) in mn_topo.links():
        switch = None
        host= None
        if x.startswith("h") and y.startswith("s"):
            switch = y
            host = x
        elif y.startswith("h") and x.startswith("s"):
            switch = x
            host = y
        else:
            continue
        host_ip = mn_topo.nodeInfo(host)['ip'].split('/')[0]
        dst_tor_num = int(switch[1:])
        port = mn_topo.port(switch, host)[0]

        # Install entries for edge forwarding.
        add_edge_forward = p4info_helper.buildTableEntry(
            table_name="MyIngress.edge_forward",
            match_fields = {
                "hdr.ipv4.dstAddr": host_ip
            },
            action_name="MyIngress.simple_forward",
            action_params={
                "port": port,
            })
        switches[switch].WriteTableEntry(add_edge_forward, debug)

        for sw in mn_topo.switches():
            self_id = int(sw[1:])
            # Install entries to calculate get_dst_tor
            add_host_dst_tor = p4info_helper.buildTableEntry(
                table_name="MyIngress.get_dst_tor",
                match_fields = {
                    "hdr.ipv4.dstAddr": host_ip
                },
                action_name="MyIngress.set_dst_tor",
                action_params={
                    "dst_tor": dst_tor_num,
                    "self_id": self_id
                })
            switches[sw].WriteTableEntry(add_host_dst_tor, debug)



def main(p4info_file_path, bmv2_file_path, topo_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Load the topology from the JSON file
        switches, mn_topo = load_topology(topo_file_path)

        # Establish a P4 Runtime connection to each switch
        for bmv2_switch in switches.values():
            bmv2_switch.MasterArbitrationUpdate()
            print "Established as controller for %s" % bmv2_switch.name

        # Load the P4 program onto each switch
        for bmv2_switch in switches.values():
            bmv2_switch.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                                    bmv2_json_file_path=bmv2_file_path)
            print "Installed P4 Program using SetForwardingPipelineConfig on %s" % bmv2_switch.name

        install_smart_mcast(mn_topo, switches, p4info_helper)
        install_tables(mn_topo, switches, p4info_helper)

    except KeyboardInterrupt:
        print " Shutting down."
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/switch.p4info')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/switch.json')
    parser.add_argument('--topo', help='Topology file',
                        type=str, action="store", required=False,
                        default='topology.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print "\np4info file not found: %s\nHave you run 'make'?" % args.p4info
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print "\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json
        parser.exit(1)
    if not os.path.exists(args.topo):
        parser.print_help()
        print "\nTopology file not found: %s" % args.topo
        parser.exit(1)
    main(args.p4info, args.bmv2_json, args.topo)
