/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
typedef bit<9> port_id_t;
typedef bit<8> util_t;
typedef bit<24> tor_id_t;
typedef bit<48> time_t;

/* Constants about the topology and switches. */
const port_id_t NUM_PORTS = 255;
const tor_id_t NUM_TORS = 512;
const bit<32> EGDE_HOSTS = 4;

/* Declaration for the various packet types. */
const bit<16> TYPE_IPV4 = 0x800;
const bit<8> TYPE_HULA = 0x42;
const bit<32> MAX_TUNNEL_ID = 1 << 16;
const bit<32> MULTICAST = 0xe0000001;

/* Tracking things for flowlets */
const time_t FLOWLET_TOUT = 3000;
const time_t KEEP_ALIVE_THRESH = 10000;

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

header hula_t {
    bit<24> dst_tor;
    bit<8> path_util;
}

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

struct metadata {
    bit<8> nxt_hop;
    bit<32> self_id;
    bit<32> dst_tor;
}

struct headers {
    ethernet_t   ethernet;
    ipv4_t       ipv4;
    hula_t       hula;
}

/*************************************************************************
*********************** P A R S E R  ***********************************
*************************************************************************/

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            TYPE_IPV4: parse_ipv4;
            default: accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
          TYPE_HULA: parse_hula;
          default: accept;
        }
    }

    state parse_hula {
        packet.extract(hdr.hula);
        transition accept;
    }

}

/*************************************************************************
************   C H E C K S U M    V E R I F I C A T I O N   *************
*************************************************************************/

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}


/*************************************************************************
**************  I N G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    /****** Registers to keep track of utilization. *******/

    // Keep track of the port utilization
    register<util_t>((bit<32>) NUM_PORTS) port_util;
    // Keep track of the last time port utilization was updated for a dst_tor
    register<time_t>((bit<32>) NUM_TORS) update_time;
    // Best hop for for each tor
    register<port_id_t>((bit<32>) NUM_TORS) best_hop;
    // Last time a packet from a flowlet was observed.
    register<time_t>((bit<32>) 1024) flowlet_time;
    // The next hop a flow should take.
    register<port_id_t>((bit<32>) 1024) flowlet_hop;
    // Keep track of the minimum utilized path
    register<util_t>((bit<32>) NUM_TORS) min_path_util;

    /******************************************************/

    counter(MAX_TUNNEL_ID, CounterType.packets_and_bytes) ingressTunnelCounter;
    counter(MAX_TUNNEL_ID, CounterType.packets_and_bytes) egressTunnelCounter;

    action drop() {
        mark_to_drop();
    }

    /*
    action hula_logic(ipv4_t ipv4_header, hula_t hula_hdr) {
        time_t curr_time = standard_metadata.ingress_global_timestamp;
        bit<32> dst_tor = (bit<32>) hula_hdr.dst_tor;

        util_t tx_util;
        port_util.read(tx_util, (bit<32>) standard_metadata.ingress_port);

        // Process a HULA probe
        if (ipv4_header.protocol == TYPE_HULA) {
            util_t mpu; time_t up_time;
            min_path_util.read(mpu, dst_tor);
            update_time.read(up_time, dst_tor);

            if(hula_hdr.path_util < tx_util) hula_hdr.path_util = tx_util;

            if(hula_hdr.path_util < hula_hdr.path_util ||
               curr_time - up_time > KEEP_ALIVE_THRESH) {

                min_path_util.write(dst_tor, hula_hdr.path_util);
                best_hop.write(dst_tor, standard_metadata.ingress_port);
                update_time.write(dst_tor, curr_time);
            }

            min_path_util.read(mpu, dst_tor);
            hdr.hula.path_util = mpu;
        }
        else {
        }
    }
    */

    /***** Implement mapping from dstAddr to dst_tor ********/
    // Uses the destination address to compute the destination tor and the id of
    // current switch. The table is configured by the control plane.
    action set_dst_tor(tor_id_t dst_tor, tor_id_t self_id) {
        meta.dst_tor = (bit<32>) dst_tor;
        meta.self_id = (bit<32>) self_id;
    }

    // Used when matching a probe packet.
    action dummy_dst_tor() {
        meta.dst_tor = 0;
        meta.self_id = 1;
    }

    table get_dst_tor {
        key= {
          hdr.ipv4.dstAddr: exact;
        }
        actions = {
          set_dst_tor;
          dummy_dst_tor;
        }
        default_action = dummy_dst_tor;
    }

    /***********************/

    /********* Implement forwarding for edge nodes. ********/
    action simple_forward(egressSpec_t port) {
        standard_metadata.egress_spec = port;
    }

    table edge_forward {
        key = {
          hdr.ipv4.dstAddr: exact;
        }
        actions = {
          simple_forward;
          drop;
        }
        size = EGDE_HOSTS;
        default_action = drop();
    }

    /******************************************************/

    apply {
        drop();
        get_dst_tor.apply();
        if (hdr.hula.isValid()) {
          standard_metadata.mcast_grp = (bit<16>)standard_metadata.ingress_port;
        }
        if (meta.dst_tor == meta.self_id) {
            edge_forward.apply();
        }
    }
}

/*************************************************************************
****************  E G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {  }
}

/*************************************************************************
*************   C H E C K S U M    C O M P U T A T I O N   **************
*************************************************************************/

control MyComputeChecksum(inout headers  hdr, inout metadata meta) {
     apply {
        update_checksum(
            hdr.ipv4.isValid(),
            { hdr.ipv4.version,
              hdr.ipv4.ihl,
              hdr.ipv4.diffserv,
              hdr.ipv4.totalLen,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.fragOffset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16);
    }
}

/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.hula);
    }
}

/*************************************************************************
***********************  S W I T C H  *******************************
*************************************************************************/

V1Switch(
MyParser(),
MyVerifyChecksum(),
MyIngress(),
MyEgress(),
MyComputeChecksum(),
MyDeparser()
) main;
