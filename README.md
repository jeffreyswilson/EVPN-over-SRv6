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
that follows in Phase 3. Skipped: MPLS/SR-MPLS restricted to 7250 IXR/7730 SXR chassis,
license-required -- not available on this lab's ixr-d3 platform.

### Phase 3 -- SRv6 migration (BLOCKED -- see NOTES.md 7/22/26)
Replace SR-MPLS with SRv6: locator/function ID structure, ISIS SRv6 extensions, IPv6
dataplane. This is the underlay the repo name originally committed to. Blocked: SRv6
restricted exclusively to 7730 SXR -- narrower than Phase 2's restriction, also
unavailable on ixr-d3. Superseded by the Phase 4 pivot below; retained here as a
documented dead end, not scrubbed from the record.

### Phase 4 -- EVPN over VXLAN, single tenant (`labs/02-l2evpn-overlay`)
BGP EVPN control plane over a VXLAN data plane, on top of the existing ISIS underlay --
not SRv6, per the 7/22/26 pivot. MAC/IP reachability and VPN membership between two PEs,
single tenant (VLAN 10, VNI 89526, EVI 3876). iBGP EVPN session rides ISIS-learned
loopback reachability directly -- no underlay BGP needed.
Note: Nokia's own official L2 EVPN tutorial series uses an eBGP underlay (RFC7938)
rather than ISIS -- overlay/EVPN content from that tutorial is being reused here, but
its underlay choice is not; this repo keeps ISIS from Phase 1.
**Status: complete, verified reproducible (destroy/redeploy from `startup-configs/`).**

### Phase 5 -- Multi-tenant EVPN, trunk-access pivot (`labs/02-l2evpn-overlay`)
Second tenant (VLAN 20, VNI 89527, EVI 3877) added to the Phase 4 deployment. Leaf-facing
access port retagged from untagged to a uniform VLAN 10+20 trunk (no mixed tagged/
untagged on a single port); per-leaf VLAN-aware Linux bridge inserted downstream,
presenting untagged/PVID access ports to four test servers (two per tenant). VLAN 1
explicitly excluded from all bridge ports. Node count: 10 (was 6 end of Phase 4).
**Status: complete, verified reproducible.**

### Phase 6 -- Symmetric IRB, L2/L3 integration (`labs/02-l2evpn-overlay`)
Inter-tenant L3 routing added atop Phases 4-5's L2-only EVPN via symmetric
integrated routing and bridging (IRB): new ip-vrf `vrf-l3`, IRB subinterfaces
dual-bound into each tenant's mac-vrf and the ip-vrf, anycast gateways
(192.168.0.254/24, 192.168.1.254/24, identical both leaves), new L3 VNI 89528 /
EVI 3878 distinct from the two L2 VNIs. Required EVPN ARP/ND synchronization
(`ipv4 arp evpn advertise dynamic` on every IRB subinterface) for cross-leaf
resolution of hosts never locally attached. Separately required a static
cross-tenant route on each server container (`topology.clab.yml`), without
which no host could route cross-subnet traffic regardless of leaf-side
config -- see NOTES.md for both root-cause writeups (7/24 leaf-side fix,
7/25 server-side fix).
**Status: complete, verified reproducible (full 12-pair cross-tenant/cross-leaf
matrix, 0% loss, confirmed across two cold destroy/deploy cycles).**

### Phase 7 -- Intent-based deployment (`labs/02-l2evpn-overlay/automation`)
Structured, programmatic generation of Phases 4-6's startup-configs from a
single declarative source (`automation/intent.yml`) instead of hand-maintained
per-node JSON. Jinja2 templates (`leaf.json.j2`, `spine.json.j2`) render
per-device startup-config from intent.yml's leaves/spines/tenants/fabric
sections; `render.py` drives the render+validate+write loop (json.loads()
schema validation before write, one output file per device).
Interface-naming translation (containerlab's `e1-N` short form vs. SR Linux's
native `ethernet-1/N`) is handled once, at the render boundary, via a Jinja
filter -- intent.yml itself stays in containerlab's vocabulary throughout,
matching topology.clab.yml rather than needing two hand-synced dialects.
**Status: complete.** Both templates validated by diffing rendered output
against the live-verified startup-configs from Phases 4-6 (leaf1/leaf2,
spine1/spine2) -- differences are whitespace/formatting only. Spine template
additionally validated by a live cold-boot round-trip: containerlab pointed
directly at `automation/output/` in place of the hand-maintained
`startup-configs/`, full 12-pair cross-tenant/cross-leaf matrix, 0% loss.

## Repo conventions

- `.gitignore` excludes `clab-*/` runtime directories (generated per deployment: node
  configs, certs, SSH keys -- reproducible from topology files + this repo, not source).
- Default SR Linux credential (`NokiaSrl1!`) is a known default in lab configs -- checked
  before any push, not committed as a live credential elsewhere.
- Addressing scheme (Phase 1): point-to-point /30 per link, `192.168.<spine><leaf>.0/30`,
  spine end `.1`, leaf end `.2`.
- Addressing scheme (Phase 4-5): tenant subnets `192.168.<tenant>.0/24` (tenant1 = 0,
  tenant2 = 1); VNI/EVI numbering follows a phone-keypad letters-to-digits scheme, not
  tutorial defaults.
- Addressing scheme (Phase 6): anycast gateways at `.254` in each tenant /24,
  chosen to avoid collision with srv1-4's `.1`/`.2` addresses; VRID 10/20
  mirrors the tenant VLAN IDs.
