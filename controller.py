#!/usr/bin/env python2
import argparse, re, grpc, os, sys, json, subprocess
from time import sleep
import networkx as nx

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utils/'))
import run_exercise
import p4runtime_lib.bmv2
from p4runtime_lib.switch import ShutdownAllSwitchConnections
import p4runtime_lib.helper
from p4runtime_lib.convert import decodeMac, decodeIPv4

# Turn on dry run mode
debug = False

# Directory for storing simple_switch_CLI commands
ssc_dir = "config/"

def printGrpcError(e):
    """
    Helper function to print a GRPC error

    :param e: the error object
    """

    print "gRPC Error:", e.details(),
    status_code = e.code()
    print "(%s)" % status_code.name,
    traceback = sys.exc_info()[2]
    print "[%s:%d]" % (traceback.tb_frame.f_code.co_filename, traceback.tb_lineno)

def load_topology(topo_file_path):
    """
    Helper function to load a topology

    :param topo_file_path: the path to the JSON file containing the topology
    """

    switch_number = 0
    switches = {}
    with open(topo_file_path) as topo_data:
        j = json.load(topo_data)
    json_hosts = j['hosts']
    json_switches = j['switches'].keys()
    json_links = run_exercise.parse_links(j['links'])
    mn_topo = run_exercise.ExerciseTopo(json_hosts, json_switches, json_links, "logs")
    for switch in mn_topo.switches():
        switch_number += 1
        bmv2_switch = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name=switch,
            address="127.0.0.1:%d" % (50050 + switch_number),
            device_id=(switch_number - 1),
            proto_dump_file="logs/%s-p4runtime-requests.txt" % switch)
        switches[switch] = bmv2_switch

    return (switches, mn_topo)

# Generate a simple UID for dst_id of each host
def host_to_dst_id(hosts):
    return dict(zip(hosts, range(1, len(hosts) + 1)))

def write_simple_switch_config(name, contents):
    file = open(ssc_dir + name, "w")
    file.write(contents)

def mcast_grp_command(mcast_id, port_ids, handle_id):
    port_seq = " ".join(str(e) for e in port_ids)
    create = "mc_mgrp_create " + str(mcast_id)
    node = "mc_node_create 0 " + port_seq
    assoc = "mc_node_associate " + str(mcast_id) + " " + str(handle_id)
    return create + "\n" + node + "\n" + assoc

# Assumes switches are numbered as s\d+
def run_mcast_commands(switches):
    switch_reg = re.compile(r"^s(\d+)$")
    for switch in switches:
        switch_port = 9090 + int(switch_reg.search(switch).group(1))
        cmd = "simple_switch_CLI --thrift-port %d < config/%s" % (switch_port, switch)
        print "Running", cmd
        print(subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True))

# Creates multicast groups. The [i]th mcast group forwards packets to all
# ports except [i].
def install_mcast(mn_topo, switches, p4info_helper):
    G = nx.Graph()
    G.add_edges_from(mn_topo.links())
    for switch in mn_topo.switches():
        command = ""
        adjacents = map(lambda (_, a): a, G.edges(switch))
        for adj in adjacents:
            mcast_adjs = filter(lambda a: a != adj, adjacents)
            mcast_ports = map(lambda a: mn_topo.port(switch, a)[0], mcast_adjs)
            ingress_port = mn_topo.port(switch, adj)[0]
            cmd = mcast_grp_command(ingress_port, mcast_ports, switches[switch].getAndUpdateHandleId())
            command += (cmd + "\n")
        write_simple_switch_config(switch, command)
    run_mcast_commands(mn_topo.switches())

def install_smart_mcast(mn_topo, switches, p4info_helper):
    # Note(rachit): Hosts are always considered downstream.
    def is_upstream(x, y):
        return x[0] == y[0] and int(x[1]) < int(y[1])

    G = nx.Graph()
    G.add_edges_from(mn_topo.links())
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
            cmd = mcast_grp_command(ingress_port, mcast_ports, switches[switch].getAndUpdateHandleId())
            command += (cmd + "\n")
        write_simple_switch_config(switch, command)
    run_mcast_commands(mn_topo.switches())

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
