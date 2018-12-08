# HULA hoop

Implementation of the [HULA](https://conferences.sigcomm.org/sosr/2016/papers/sosr_paper67.pdf) algorithm.

## Requirements

- `bvm2`
- `mininet`
- p4 16 compiler
- PI

## Building and running

- Generate topology using `topology-generation/fattree.py` script or use the default one.
- Run `make` and wait for mininet to start up.
- Run `./controller.py` to configure the data plane.

The switches are now configured, however, at this point, the hosts don't have
routes to hosts not on their rack. To establish a route to a host `hn`:

- Run `xterm hn` from mininet CLI.
- In the terminal, run `./test-scripts/probe.py`. This script sends probes from
  the current host every `1s`.

This will send a probe from `hn` to every other node and establish a path to
`hn` from every other node. It will also establish a path to every other host
connected the same ToR as `hn`. Repeat this for all node to establish a
connection to them.

Use the `./test-scripts/receieve` and `./test-script/send` script to view
incoming packets and send packets to other hosts respectively.

## Implementation details

### Topology Generation

Since Fat tree topologies are commonly used in datacenters, the paper uses them
for evaluation. However, HULA doesn't require any specific topology to work
correctly. For this project, any topology with a notion of upstream and
downstream links will be sufficient.

The project assumes the following naming scheme to distinguish upstream and
downstream links: A switch in the `n`th tier has the form `sm` where `100 * n <
m < 100 * (n + 1)`.

### Multicast Implementation

The paper implements a smart form of multicast for probe replication that uses
a notion of upstream and downstream links. The smart multicast implementation
uses the aforementioned naming convention.

At the p4 level, the implementation uses `simple_switch_CLI` to program each
switch by generating configuration commands for each switch in `config/`. The
pseudocode for the smart multicast is:

```
if packet from downstream link:
    replicate on all links except ingress
else:
    replicate only on downstream links
```

which is computed into simple multicast groups. The controller creates a
mapping from `ingress_port` to multicast group where each multicast group
does the right thing.

**Note**: The implementation of multicast groups in here does not leverage
the probe optimization from the paper (Section 4.5).

**Note**: There is also code in `util` to send the correct messages to the
software switch, however, bmv doesn't completely implement message to the
Packet Replication Engine (PRE) (see [this](https://github.com/p4lang/PI/blob/d4e5aff15b3f77af578704fe03b82a15814da8f0/proto/frontend/src/device_mgr.cpp#L1772)).

### Probe packets

Probe packets are the main component of the HULA protocol. A probe packet
originates from a src ToR switch and gets replicated throughout the network.
The path utilization and the hop information from the probe is used to
configure the best hop to get to the ToR where the probe originated.

The probe packet contains two headers: `dst_tor` and `path_util`. The parsing
and deparsing parts of the code are trivial for the new headers.

### Destination ToR mapping

The forwarding tables need to know the ToR ID associated with each switch in
order to implement forwarding. Namely, it makes two decisions based on this
infrormation:

1. If a data packet has reached its required ToR, forward to the rack switch.
2. If not, use the destination ToR to find the next best hop.

In the implementation, this infromation is stored in two `metadata` fields:
`self_id` and `dst_tor`. The control plane configures `get_dst_tor` table
to correctly extract this information for all switches.

### Link utilization

Hula requires a notions of link utilization associated with each incoming port
on a switch. The link utilization is computed by the `update_ingress_statistics`
action using the formula `u = pk_l + u * (1 - dt/t)` where `pk_l` is the size
of the packet, `dt` is the time since last update, and `t` is a constant.

## Evaluation

### Coping with link failures

We'll be working with `h1`, `h2`, and the switches that connect. If you'd like to
use a different pair of hosts, take a look at `./topology-generation/foo.png` to
figure out which switches connect them.

- Run `make` and wait for mininet to start up.
- Run `./controller.py` to configure the multicast groups and tables.
- Run `link s104 s211 down` and `link s104 c210 down` in mininet CLI. This removes all paths
  from `h1` to `h10`.
- Run `xterm h1 h10 h10` in mininet CLI to create one terminal for `h1` and two for `h10`.
- In the first `h10` run `./test-scripts/probe.py` to start sending probes from `h10`.
- In the second `h10` instance, run `./test-scripts/receive.py` to display incoming packets.
- In the `h1` terminal, run the following to continously send packets to `h10`.
  With the current setup, none of the packets will reach `h10`.

```
./test-scripts/send.py 10.0.104.10 "h1" -1
```

- Now run `link s104 s211 up` in the mininet CLI to bring up the link. There is
  now a path from `h1` to `h10`.
- After a short delay, note that packet from `h1` have started arriving to `h10`.
  The HULA probes have detected and coped with link failures!

## Experience with P4

- The semantics of what variables are shared between the controls is not always
  clear from the program. For example, if I define an array in the ingress control,
  will it carry state across different invocations of the ingress? What makes
  registers unique to allow them to carry the state across invocations? This is
  what Andy Fingerhut from the p4 slack had to say:

      P4_16 header stack syntax looks like an array, and in many ways is, but
      only for arrays of values of some header type, and they do not preserve
      their value after finishing processing one packet.  Like other header
      types, their value disappears after a packet is finished processing

- No conditionals allowed in table actions. Needed to manually turn the code
  straightline. Painful.

## Code sources

- Built upon the skeleton code from homework03 for CS6114 fall 18, by Nate Foster, Cornell University.
- Fat tree topology generation code taken from the [Frenetic](https://github.com/frenetic-lang/frenetic) repository.
