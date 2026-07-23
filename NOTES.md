# Notes / gotchas

Technical patterns encountered while building the ISIS underlay (Phase 1) worth
carrying forward into later phases, since some recur.

## SR Linux: independent enable layers

Several features require enabling at multiple layers that don't imply each other --
setting one and assuming the others follow silently fails without error, until the
final commit surfaces it (or doesn't, and the feature just stays down):

- Subinterface existence: `set / interface ethernet-1/1 subinterface 0 type routed`
  must exist before anything else references it -- setting admin-state on a
  not-yet-created subinterface index is accepted into the candidate diff but fails
  at commit once something else tries to resolve it.
- Subinterface admin-state (separate from the base interface's own admin-state).
- IPv4 protocol admin-state on the subinterface (`... subinterface 0 ipv4
  admin-state enable`) -- separate from both the subinterface's admin-state and
  the address object itself. An address can be present and correct while this
  layer is still disabled, and `show interface` will report `no-ip-config` in a
  way that looks like the address is missing when it isn't -- check
  `info from state interface ... subinterface 0` for the full tree if this happens.
- Network-instance binding: referencing a subinterface from `protocols isis
  instance ISIS interface ...` does not add it to the network-instance's interface
  list. That's `set / network-instance default interface <name>.<idx>`, a separate
  explicit step -- confirm with `show network-instance default interfaces *`.
- ISIS per-interface `ipv4-unicast admin-state enable` -- the interface-level
  child needs its own explicit admin-state, distinct from the global ISIS instance
  `ipv4-unicast admin-state enable`.

General takeaway: when something looks correctly configured but isn't functioning,
check one layer down in the tree before assuming the config itself is wrong.
`info from state interface ...` (full state tree) is more reliable than `show
interface` (summary) for catching this class of gap.

## containerlab exec + SR Linux CLI

`containerlab exec --cmd "show ..."` fails -- `show` isn't a shell binary, it's a
mode inside SR Linux's CLI shell. Wrap it:
```
containerlab exec -t topology.clab.yml --cmd 'sr_cli "show interface ethernet-1/1"'
```
Note the nested quoting: outer single quotes for the shell, inner double quotes so
`sr_cli` receives the multi-word command as one argument. Runs the same command
across all nodes in one call, labeled per-node in output.

## Config capture / reproducibility

`clab-<labname>/<node>/config/config.json` reflects committed running config and
is what to copy into a tracked `startup-configs/` directory, referenced from the
topology YAML's `startup-config:` field per node. `checkpoint-0.json` in the same
directory is the factory-default checkpoint Containerlab creates on first deploy --
not current state, don't confuse the two.

`aaamgr_local_user.json` in that same directory holds credential material --
excluded explicitly in `.gitignore`, not just via the blanket `clab-*/` rule.

Validate any capture by destroy + redeploy + re-check state, not by assuming the
copy worked.

## Architecture verification habit

Any new image pulled (not just the first one) gets:
```
docker image inspect <image> -f '{{.Architecture}}'
```
arm64 host, arm64 images only -- a wrong pull silently reintroduces emulation.

## Open item carried into Phase 2

SR-MPLS node SID advertisement into ISIS: configured via a network-instance-level
protocol-independent `local-prefix-sid` (not inside the ISIS instance block
directly). Unconfirmed whether SR-ISIS TLV advertisement to neighbors follows
automatically from this path, or needs an explicit toggle inside the ISIS instance
itself -- verify via adjacency/LSDB inspection before assuming either way.

## Phase 2 decision -- 7/22/26

Attempted Phase 2 (SR-MPLS extensions) on spine1: `set / system mpls ...`
rejected outright -- `mpls` is not a valid child of `system` in this
node's schema (confirmed via CLI completion list and `info system`
output, not a typo).

Root cause, confirmed via containerlab docs + netlab.tools platform
caveats: MPLS/SR-MPLS on SR Linux is scoped to the 7250 IXR and 7730 SXR
chassis families, license-required. This lab runs `ixr-d3` (7220 IXR-D3),
a fixed-configuration platform that runs license-free by design -- MPLS
was never in scope for this chassis type. Not an arm64/preview-build
issue; confirmed independent of architecture.

Decision: skip Phase 2 as a discrete step. Cost/benefit didn't clear:
MPLS is a canon.md Permanent gap (manage via disclosure, not close via
lab work -- different treatment than EVPN/VXLAN or Ansible/Terraform,
which were promoted out of Permanent specifically because lab work
closed them). Phase 2's only job was isolating "ISIS carries SR info"
from the IPv6-dataplane jump before Phase 3 -- scaffolding value, not
a standalone artifact this repo needs. License acquisition + chassis-
type swap (`ixr-d3` -> a 7250 IXR variant) costs real time against a
step that was never the destination; repo name and stated deliverable
are SRv6, not SR-MPLS.

Proceeding directly to Phase 3 (SRv6 migration) on the existing
`ixr-d3` topology. SRv6 chassis-type support on IXR-D3 is unconfirmed
as of this note -- next session's first action is finding out live,
not assuming parity with the MPLS restriction just hit.

## Phase 3 decision -- 7/22/26

Attempted Phase 3 (SRv6 migration) on spine1: `segment-routing srv6`
not available on this platform, confirmed live via CLI. Root cause,
confirmed via Nokia's own SRv6 documentation: SRv6 is currently
supported exclusively on 7730 SXR platforms -- narrower than the
SR-MPLS restriction hit in Phase 2 (7250 IXR + 7730 SXR). This chassis
(`ixr-d3`) cannot reach SRv6 regardless of license.

## Pivot decision -- 7/22/26

Repo destination (EVPN over SRv6) is not achievable on this hardware
profile without a chassis-type change to 7730 SXR plus a Nokia license.
Decision: pivot to EVPN over a VXLAN data plane instead of SRv6.

Confirmed via Nokia's own EVPN for Layer 3 guide: EVPN-VXLAN is
supported directly on 7220 IXR-D2/D3/D2L/D3L -- this exact chassis --
with no license required. Contrast: EVPN-MPLS remains restricted to
7250 IXR / 7730 SXR, same pattern as the SR-MPLS/SRv6 walls just hit,
because EVPN-MPLS needs the MPLS dataplane and EVPN-VXLAN doesn't.
Nokia's own official L2 EVPN tutorial (learn.srlinux.dev) runs this
exact configuration on `ixr-d2`/`ixr-d3` nodes with no license file
referenced anywhere in it -- direct, run-it-yourself precedent.

Repo name retained (not renamed to drop "SRv6"). The SRv6 attempt,
correctly diagnosed via live CLI + vendor docs across two real platform
walls, is part of the story this repo tells, not something to scrub.
README carries an explanatory note rather than a silent rewrite.

Effective phase order going forward: 0 -> 1 -> 4 -> 5. Phases 2 and 3
are retained below as documented dead ends -- Phase 4 depends only on
Phase 1's ISIS underlay (loopback reachability for VTEP peering), not
on 2 or 3, so it's unblocked and moves up next.

## Phase 4 -- EVPN over VXLAN, verified 7/22/26

Built on the existing ISIS underlay (labs/01-underlay), no changes to
that phase. New lab folder labs/02-l2evpn-overlay/ -- self-contained
copy of the underlay topology + startup-configs, plus two Linux test
containers (srv1/srv2) wired to leaf1/leaf2 ethernet-1/3, per the
Option A decision (self-contained repo, no host-VM bridging
dependency).

Config: iBGP EVPN session between leaf1 (10.0.0.3) and leaf2 (10.0.0.4)
directly, riding on ISIS-learned loopback reachability -- no underlay
BGP needed, unlike Nokia's own tutorial (which uses eBGP underlay +
iBGP overlay). VXLAN tunnel-interface vxlan1, VNI 89526. MAC-VRF
vrf-1, EVI 3876, route-target target:64512:3876. Numbering scheme:
phone-keypad letters-to-digits of VXLAN/EVPN, not tutorial defaults.

Verification, full chain confirmed:
- ISIS underlay: leaf1 route-table shows 10.0.0.4/32 (leaf2 loopback)
  active via both spines, ECMP, metric 20 -- fabric-wide reachability
  before any BGP config touched it.
- iBGP EVPN session: established, AFI/SAFI evpn, [1/1/1] routes.
- Type 3 (IMET) route exchanged -- auto-discovery/flooding-list setup.
- Dataplane: srv1 (192.168.0.1) <-> srv2 (192.168.0.2) ping, 0% loss
  both directions. ARP tables confirm correct remote MACs learned.
- Bridge-table: srv1's MAC learnt (local), srv2's MAC evpn-tagged
  vtep:10.0.0.4 vni:89526 (remote, via EVPN).
- Type 2 (MAC/IP) route confirmed for srv2's MAC: RD 10.0.0.4:3876,
  label 89526, status used/valid/best -- the actual control-plane
  route underpinning the working ping, not inferred from ping success
  alone.

This is the repo's actual deliverable, achieved on the same ixr-d3
chassis that rejected SR-MPLS (Phase 2) and SRv6 (Phase 3) outright.
Pivot from the original SRv6-underlay premise to EVPN-VXLAN is now a
proven, not theoretical, substitution.

IRB (integrated routing/bridging) noted as a term encountered during
verification (0 IRB MACs in bridge-table, expected) -- not relevant to
this phase's scope (pure Type 2 L2 EVPN, single subnet). Would become
relevant for a future L3/multi-subnet EVPN phase; flagged there rather
than resolved here since it's out of scope for what was built.

Next: containerlab save to snapshot this running state into
02-l2evpn-overlay/startup-configs/*.json, per the plan agreed before
this phase began -- makes the phase reproducible from a fresh deploy,
not just from this session's live CLI history.

## Phase 4 reproducibility confirmed -- 7/22/26

containerlab save captured live EVPN config into leaf1/leaf2 config.json.
Copied into startup-configs/leaf1.json and leaf2.json (spine1/spine2
startup-configs unchanged -- byte-identical to Phase 1, confirmed via
file size match, no EVPN config ever touched them).

Destroyed and redeployed labs/02-l2evpn-overlay/ from these
startup-configs alone, no live CLI re-entry. srv1 <-> srv2 ping
succeeded immediately post-deploy. This confirms the phase is fully
reproducible from a fresh clone -- same destroy+redeploy validation
pattern established in Phase 1.

## Phase 5 (multi-tenant EVPN, trunk-access pivot)

In progress, started 2026-07-23. Second tenant (VLAN 20, VNI 89527, EVI 3877)
added.  Design decision: rejected mixed tagged/untagged access on a single
leaf port (Option A/B tradeoff discussed, not detailed here -- see session chat
if recovered later). Chosen design: leaf-facing e1-3 retagged from
untagged-access to a pure VLAN 10+20 trunk; per-leaf VLAN-aware Linux bridge
(sw1/sw2) inserted downstream, presenting untagged/PVID access ports to servers.
New nodes: sw1, sw2, srv3, srv4 (4 added, tally: was 6 nodes end of Phase 4, now
10).  VLAN 1 explicitly dropped on bridge uplink ingress -- no default-VLAN
leakage toward leaf. Not yet verified end-to-end; verification list TBD at phase
close, same discipline as Phase 4's route-by-route confirmation.

## Phase 6 (planned) -- symmetric IRB, L2/L3 integration

Goal: extend Phase 5's two-tenant L2 EVPN into inter-tenant L3 routing --
integrated routing and bridging (IRB), symmetric mode, per EVPN's own
architecture rather than a bolt-on static route.

Scope, incremental over Phase 5, no rebuild of existing L2 config:
- New ip-vrf network-instance per leaf (name TBD, e.g. vrf-l3-tenant),
  distinct type from the existing mac-vrf vrf-1/vrf-2.
- IRB subinterfaces (irb0.1 for VLAN 10/vrf-1, irb0.2 for VLAN 20/vrf-2)
  bridging each mac-vrf into the ip-vrf -- one IRB per tenant subnet,
  bound into both the mac-vrf (bridged side) and the ip-vrf (routed
  side) simultaneously.
- Anycast gateway IP + shared virtual MAC per subnet (192.168.0.254/24
  for VLAN 10, 192.168.1.254/24 for VLAN 20 -- numbering TBD, avoid
  colliding with existing host addresses), identical on leaf1 and
  leaf2 -- symmetric IRB requires the gateway to be answerable
  identically at either leaf, not anchored to one.
- New L3 VNI (distinct from the two L2 VNIs 89526/89527) carrying
  routed inter-subnet traffic between leaves -- symmetric IRB's
  defining trait vs asymmetric: routing happens at the ingress leaf,
  packet re-encapsulated into the L3 VNI, decapsulated and bridged
  out locally at the egress leaf. Asymmetric IRB (routes locally at
  ingress, bridges remotely) was considered and rejected -- symmetric
  is the more commonly deployed/documented pattern and matches Nokia's
  own EVPN-for-L3 guide already used as precedent in the Phase 3->4
  pivot.
- New route-target for the ip-vrf, separate community from the two
  mac-vrf RTs (target:64512:3876 / :3877) -- L3 reachability
  advertised independently of L2 MAC reachability, per EVPN's
  RT2-carries-both-but-RT5-or-VRF-RT-scopes-L3 design.

Open items, not yet resolved:
- [UNCERTAIN] whether SR Linux's srl_nokia-bgp-evpn schema expresses
  the L3 VNI/ip-vrf EVPN binding as a sibling block to the existing
  mac-vrf bgp-instance, or requires a materially different config
  tree -- check live schema (`info` under the candidate ip-vrf's
  protocols) before drafting concrete JSON, same discipline as the
  Phase 5 RT-leaf-list schema check that was deferred pending live
  `info` output.
- Anycast-gw feature is in this platform's enabled-yang-features list
  (srl_nokia-features:anycast-gw, confirmed present in both leaf
  startup-configs) -- feature exists on ixr-d3, no repeat of the
  Phase 2/3 chassis-restriction pattern expected, but not yet verified
  against symmetric-IRB specifically vs anycast-gw's other use cases.
- Route type surface expands: Type 2 (MAC/IP) routes now carry an L3
  label alongside the existing L2 label (dual-label, per symmetric
  IRB spec) -- verification step needs to confirm both labels present,
  not just route presence. Type 5 (IP Prefix) routes are out of scope
  for this phase (only directly-connected subnets, no external/
  aggregate prefix advertisement) -- flag as a possible Phase 7 if the
  lab grows toward WAN-facing/L3-gateway scope.
- Test plan: srv1 (192.168.0.1, tenant1) -> srv3 (192.168.1.1, tenant2)
  ping should now succeed (contrast with Phase 5, where this same
  ping correctly failed due to isolated bridge tables) -- this
  transition, fail-by-design in Phase 5 to succeed-by-design in
  Phase 6, is itself the verification signal that L3 integration is
  live and scoped correctly, not a regression.

Not started -- planning entry only, precedes any live config change.
