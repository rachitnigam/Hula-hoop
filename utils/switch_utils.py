import sys, json, re, subprocess
import run_exercise
import p4runtime_lib.bmv2

switch_reg = re.compile(r"^s(\d+)$")

def run_ssc_cmd(switch, cmd, debug=True):
    switch_port = 9090 + int(switch_reg.search(switch).group(1))
    cmd = "simple_switch_CLI --thrift-port %d <<EOF \n%s EOF" % (switch_port, cmd)
    if debug:
        print "Running", cmd
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    return out

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
