# EVPN-over-SRv6

Learning curriculum: implementing EVPN over an SRv6 underlay using Nokia SR Linux,
Containerlab, on a single ARM64 Ubuntu VM (Parallels, M4 MacBook Pro).

## Environment

- VM: `clab-srl-arm64`, Ubuntu 26.04 Server arm64, 6 vCPU / 12GB RAM / 64GB disk, Parallels
- Docker CE (native arm64, docker.com apt repo -- not snap)
- Containerlab (native arm64 install script)
- SR Linux image: `ghcr.io/nokia/srlinux:24.10.7` (arm64-native, preview status per Nokia docs;
  confirm architecture with `docker image inspect ... -f '{{.Architecture}}'` on any new pull)

No emulation layer anywhere in the stack -- Parallels uses Apple's Hypervisor.framework
(not QEMU) for the arm64 guest, and all images/binaries are arm64-native.

**Scope note (7/22/26):** This repo set out to build EVPN over an
SRv6 underlay. Phases 2 (SR-MPLS) and 3 (SRv6) hit real, vendor-
confirmed chassis restrictions on this lab's hardware profile (7220
IXR-D3, license-free) -- both features are gated to 7250 IXR / 7730
SXR on SR Linux. Pivoted to EVPN over a VXLAN data plane, which this
chassis supports without a license. Name kept -- the SRv6 attempt
and diagnosis are part of the record, not scrubbed. Full decision
trail in NOTES.md.

## Curriculum arc

### Phase 0 -- Verification (`labs/00-single-node-verify`)
Single SR Linux node, confirms image/runtime/Containerlab wiring works before scaling up.
**Status: complete.**

### Phase 1 -- Plain ISIS underlay (`labs/01-underlay`)
4-node Clos (2 spine, 2 leaf), full leaf-spine mesh, plain ISIS (no SR extensions yet).
Goal: close the ISIS operational gap left by prior SPBM-only exposure -- reading adjacency
state, LSDB, route-table, and surviving a deliberate link failure, not just instantiating
a black-box IGP.
**Status: complete.**

### Phase 2 -- SR-MPLS extensions (SKIPPED -- see decision log in NOTES.md 7/22/26)
Add segment IDs and label advertisement to the same ISIS instance, IPv4 MPLS dataplane
still in place. Isolates "ISIS now carries SR info" from the IPv6/SRv6 dataplane jump
that follows in Phase 3.

### Phase 3 -- SRv6 migration (BLOCKED -- see NOTES.md 7/22/26)
Replace SR-MPLS with SRv6: locator/function ID structure, ISIS SRv6 extensions, IPv6
dataplane. This is the underlay the repo name commits to.

### Phase 4 -- EVPN over VXLAN (`labs/02-l2evpn-overlay`) (ACTIVE NEXT -- see pivot note above)
BGP EVPN control plane over a VXLAN data plane, on top of the existing ISIS underlay --
not SRv6, per the 7/22/26 pivot. MAC/IP reachability and VPN membership between PEs.
Note: Nokia's own official L2 EVPN tutorial series uses an eBGP underlay (RFC7938)
rather than ISIS -- overlay/EVPN content from that tutorial is being reused here, but
its underlay choice is not; this repo keeps ISIS from Phase 1.

### Phase 5 -- Intent-based deployment (planned, not started)
Revisit Phases 1-4 through structured/programmatic config generation instead of manual
per-node CLI, once the manual version is fully working end to end. Deliberately sequenced
last -- automating a config not yet understood just relocates debugging into a harder-to
-inspect layer (troubleshooting generated output *and* device state simultaneously).
Candidates under consideration: gNMI-based Python (pygnmi/scrapli -- native fit for SR
Linux's gNMI-first model, avoids CLI-scraping and the class of missing-intermediate-node
errors hit manually in Phase 1), Ansible + `nokia.srlinux` collection, or Nornir +
Jinja2 templates driven off the Containerlab topology file as source of truth.

## Repo conventions

- `.gitignore` excludes `clab-*/` runtime directories (generated per deployment: node
  configs, certs, SSH keys -- reproducible from topology files + this repo, not source).
- Default SR Linux credential (`NokiaSrl1!`) is a known default in lab configs -- checked
  before any push, not committed as a live credential elsewhere.
- Addressing scheme (Phase 1): point-to-point /30 per link, `192.168.<spine><leaf>.0/30`,
  spine end `.1`, leaf end `.2`.
