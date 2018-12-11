#!/usr/bin/env python2

import json, os, sys, re

port_to_dst = {
    's100': {
        3: 's203',
        4: 's202'
    },
    's102': {
        3: 's206',
        4: 's207'
    },
    's206': {
        3: 's300',
        4: 's301'
    },
    's207': {
        3: 's302',
        4: 's303'
    },
    's203': {
        3: 's302',
        4: 's303'
    },
    's202': {
        3: 's300',
        4: 's301'
    }
}

final_hops = {
    's300': 's210 -- s104',
    's301': 's210 -- s104',
    's302': 's211 -- s104',
    's303': 's211 -- s104'
}

with open('data.json') as j:
    data = json.load(j)

hops_change = {}
for d in data:
    hops = d['best_hops']
    for src in hops:
        if src not in hops_change:
            hops_change[src] = []
        hops_change[src].append(int(hops[src]['104']))

with open('topo.dot', 'r') as t:
    topo = t.readlines()

frame_name = "frames/h1-to-h9-"
curr_frame = 1

# Generate paths from h1 to h9
for i in range(0, 60):
    # path starting from h1
    h1 = port_to_dst['s100'][hops_change['s100'][i]]
    h2 = port_to_dst[h1][hops_change[h1][i]]
    f = final_hops[h2]
    path1 = 'h1 -- s100 -- %s -- %s -- %s -- h9 [color=red,penwidth=2];' % (h1, h2, f)

    # path starting from h2
    h1 = port_to_dst['s102'][hops_change['s102'][i]]
    h2 = port_to_dst[h1][hops_change[h1][i]]
    f = final_hops[h2]
    path2 = 'h5 -- s102 -- %s -- %s -- %s -- h9 [color=blue,penwidth=2];' % (h1, h2, f)

    path = path1 + "\n" + path2

    file = "%s%s.dot" % (frame_name, str(curr_frame).zfill(2))
    with open(file, 'w') as frame_file:
        for line in topo:
            frame_file.write(re.sub(r'// %%PATH%%', path, line))
    curr_frame += 1
