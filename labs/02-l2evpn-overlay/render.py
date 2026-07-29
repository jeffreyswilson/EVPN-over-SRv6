#!/usr/bin/env python3

import argparse
from jinja2 import Environment, FileSystemLoader
import json
from pathlib import Path 
from pprint import pprint
import sys
import yaml

def srl_ifname(clab_name):
    return clab_name.replace("e1-", "ethernet-1/")

def find_leaf(data, leaf_id):
    for leaf in data["leaves"]:
        if leaf["id"] == leaf_id:
            return leaf
    return None

def get_leaf_and_peer(data, leaf_id):
    leaf = find_leaf(data, leaf_id)
    peer_id = leaf["bgp_evpn_neighbor"] # this breaks if count(leaf) > 2
    peer = find_leaf(data, peer_id)
    return leaf, peer

def find_spine(data, spine_id):
    for spine in data["spines"]:
        if spine["id"] == spine_id:
            return spine
    return None

def main():

    templates_dir = Path(__file__).parent / "automation" / "templates"
    env = Environment(loader=FileSystemLoader(templates_dir))
    env.filters["srl_ifname"] = srl_ifname
    leaf_template = env.get_template("leaf.json.j2")
    spine_template = env.get_template("spine.json.j2")

    parser = argparse.ArgumentParser(
        description="Render YAML file to intent-based network"
    )
    parser.add_argument(
        "filename",
        help="Path to YAML file"
    )
    args = parser.parse_args()

    try:
        with open(args.filename, "r", encoding="utf-8") as f:

            # Validate YAML 
            data = yaml.safe_load(f)
            # print(f"OK: '{args.filename}' is valid YAML")
            leaf_ids = [leaf["id"] for leaf in data["leaves"]]
            for leaf_id in leaf_ids:
                leaf, nbr = get_leaf_and_peer(data,leaf_id)
                leaf_rendered = leaf_template.render(
                    leaf=leaf, peer_leaf=nbr, tenants=data["tenants"], fabric=data["fabric"]
                )
            
                try:
                    json.loads(leaf_rendered)
                except json.JSONDecodeError:
                    print(f"Bad JSON rendered for leaf: {leaf_id}",file=sys.stderr)
                    sys.exit(1)

                try:
                    outfile = Path("automation/output") / f"{leaf_id}.json"
                    outfile.parent.mkdir(parents=True, exist_ok=True)
                    with open(outfile,"w") as out:
                        out.write(leaf_rendered)
                except OSError:
                    print(f"Problems writing json for {leaf_id}", file=sys.stderr)
                    sys.exit(1)

            spine_ids = [spine["id"] for spine in data["spines"]]
            for spine_id in spine_ids:
                spine = find_spine(data, spine_id)
                spine_rendered = spine_template.render( spine=spine )

                try:
                    json.loads(spine_rendered)
                except json.JSONDecodeError:
                    print(f"Bad JSON rendered for spine: {spine_id}",file=sys.stderr)
                    sys.exit(1)

                try:
                    outfile = Path("automation/output") / f"{spine_id}.json"
                    outfile.parent.mkdir(parents=True, exist_ok=True)
                    with open(outfile,"w") as out:
                        out.write(spine_rendered)
                except OSError:
                    print(f"Problems writing json for {spine_id}", file=sys.stderr)
                    sys.exit(1)
                
            sys.exit(0)

    except FileNotFoundError:
        print(f"Error: file '{args.filename}' not found", file=sys.stderr)
        sys.exit(1)

    except yaml.YAMLError as e:
        print(f"YAML validation failed for '{args.filename}':", file=sys.stderr)
        sys.exit(2)

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(3)

if __name__ == "__main__":
    main()
