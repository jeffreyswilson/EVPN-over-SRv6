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

## Phase 5 -- multi-tenant EVPN, trunk-access pivot, verified 2026-07-2x

Second tenant (VLAN 20, VNI 89527, EVI 3877, RT target:64512:3877) added
to the existing single-tenant EVPN-VXLAN deployment. Design: leaf-facing
e1-3 retagged from untagged-access to a uniform VLAN 10+20 trunk (no
mixed tagged/untagged on one port); per-leaf VLAN-aware Linux bridge
(sw1/sw2) inserted downstream, presenting untagged/PVID access ports
to servers (srv1/srv3 off sw1, srv2/srv4 off sw2). VLAN 1 explicitly
excluded from all bridge ports via vlan_default_pvid 0 at bridge
creation -- confirmed via bridge vlan show, zero vid-1 membership
including the uplink. Node count: 10 (was 6 end of Phase 4).

Config built live via SR Linux CLI (sr_cli, candidate/commit), not
scripted -- deliberate choice for CLI/tab-complete practice over
Phase 4's file-splice approach. Captured post-verification via
containerlab save into startup-configs/leaf1.json and leaf2.json.

Verification, full chain confirmed:
- Same-tenant pings: srv1<->srv2 (VLAN 10, unaffected by retag) and
  srv3<->srv4 (VLAN 20, new) both succeed.
- Cross-tenant isolation: srv1<->srv3 ping fails, as expected --
  separate mac-vrf bridge tables, no shared broadcast domain.
- Bridge-table MAC learning confirmed on both switches and both leaves,
  local and remote entries, matching Phase 4's evidentiary standard.
- Type 3 (IMET) and Type 2 (MAC/IP) routes confirmed for EVI 3877:
  RD 10.0.0.4:3877, label 89527, status used/valid/best -- via global
  route table (show network-instance default protocols bgp routes evpn
  route-type summary), not the per-vrf bgp-evpn bgp-instance command,
  which showed empty despite the routes being live (see gotcha below).
  EVI 3876/vrf-1 routes confirmed unaffected in the same table.
- Destroy + redeploy from captured startup-configs alone, zero live
  CLI re-entry -- all above re-confirmed post-redeploy. Reproducibility
  proven, same bar as Phase 4's second entry.

Gotcha for NOTES.md gotchas section: `show network-instance <vrf>
protocols bgp-evpn bgp-instance <id>` can render an empty EVPN Routes
section (Next hop/MAC-IP/IMET all None) even when the routes are live
and valid -- confirmed via cross-check against `show network-instance
default protocols bgp routes evpn route-type summary`, which showed
the same routes as used/valid/best. Don't trust the per-instance
command alone as a "no routes" signal -- cross-check the global RIB
view before concluding a fault exists.

## Phase 6 -- symmetric IRB, L2/L3 integration, verified live 2026-07-24

Extended Phase 5's two-tenant L2 EVPN into inter-tenant L3 routing via
symmetric IRB. New ip-vrf `vrf-l3` per leaf; IRB subinterfaces irb0.1
(tenant1) and irb0.2 (tenant2), each bound into both its mac-vrf and
vrf-l3 simultaneously -- that dual membership, not any special
interface type, is what implements the "integrated" part of IRB.
Anycast gateways 192.168.0.254/24 and 192.168.1.254/24, identical on
both leaves, MAC derived via `anycast-gw virtual-router-id` (10/20) --
preferred over hand-typing `anycast-gw-mac` directly: self-documenting,
one less place for a byte-for-byte cross-leaf mismatch. New L3 VNI
89528, EVI 3878, RT target:64512:3878, distinct from the two L2 VNIs
per plan.

Schema findings, useful beyond this phase:
- `network-instance type` is a closed set: `default | ip-vrf | mac-vrf`.
- `bgp-evpn` and `bgp-vpn` protocol blocks are structurally identical
  under mac-vrf and ip-vrf -- no separate ip-vrf-specific config tree.
  `bgp-vpn`'s own help text confirms it's shared: "common bgp-ipvpn and
  bgp-evpn parameters."
- IRB subinterfaces reject the `type` leaf outright at commit
  (`FailedPrecondition: type not supported on this interface`), even
  though tab-complete lists `routed|bridged|local-mirror-dest` as
  valid values for subinterfaces generally. IRB's dual L2/L3 nature
  comes entirely from being referenced in two network-instances'
  `interface` lists, not from a type declaration.
- `bridge-table proxy-arp` cannot be configured on a mac-vrf that has
  an IRB attached -- schema-enforced (`IRB interfaces cannot be
  configured with proxy-arp`), not a workaround-able error. ARP
  synchronization for IRB uses a different mechanism entirely (next
  point).

Root cause identified in the 2026-07-24 session: EVPN Type 2 (MAC/IP)
routes were advertised with the IP field empty (`0.0.0.0`) by default
-- only the anycast-gw's own address populated it. A leaf with no
local host in a given subnet (e.g. leaf2 for srv3, since symmetric IRB
makes both leaves treat every tenant subnet as "locally connected")
had no way to resolve ARP for a remote host: local ARP could never
succeed (host isn't actually there), and the MAC-only route gave it
nothing to synchronize from. Fix: `set / interface irb0 subinterface
<n> ipv4 arp evpn advertise dynamic` on every IRB subinterface, both
leaves -- pushes locally-learned dynamic ARP entries into the Type 2
route's IP field, letting remote leaves populate ARP purely from BGP.
Symptom before the fix: cross-leaf, cross-tenant pings succeeded or
failed asymmetrically depending on which host had incidentally
triggered local ARP learning first -- looked random, wasn't; every
failure traced to "destination host never locally attached to the
leaf trying to deliver to it, and its Type 2 route carried no IP."
A transient `irb-mac-address-not-programmed` chassis event during the
original multi-step commit was a red herring -- self-recovered via
interface flap, unrelated to the actual ARP/EVPN root cause; ruled out
via a clean subinterface rebuild before the real fix was found.

Verification, full matrix, all 12 same-tenant/cross-tenant/cross-leaf
combinations across all four servers, confirmed 0% loss:
srv1<->srv2, srv1<->srv3, srv1<->srv4, srv2<->srv3, srv2<->srv4,
srv3<->srv4 (each direction tested). Cross-tenant/cross-leaf pairs
(srv1<->srv4, srv2<->srv3) show ttl decrement confirming genuine
L3 routing via the L3 VNI, not bridging.

Status: verified against live CLI-built config. Reproducibility
(containerlab save -> startup-configs/ -> destroy/redeploy -> re-run
matrix cold) not yet performed -- pending, same bar as Phases 4-5
before their own reproducibility-confirmed follow-up entries.

## Phase 6 follow-up -- cold-boot reproducibility failure, 2026-07-25

First cold-boot test (`containerlab destroy && containerlab deploy`,
startup-configs captured from the 7/24 session above) failed the full
cross-tenant matrix at 100% loss, uniformly, across all 8 cross-tenant
pairs -- indistinguishable at first from the 7/24 symptom. Two
red herrings pursued and ruled out before the real cause surfaced,
kept here since both are legitimate, reusable schema findings even
though neither was the fault this time:

- `ipv4 arp host-route populate <dynamic|evpn|static>` -- controls
  whether a resolved ARP/ND entry gets promoted to a host /32 FIB
  route. Confirmed absent on cold boot, added and committed on both
  leaves, both IRB subinterfaces. Had no effect on the symptom --
  the missing host /32s turned out to be immaterial, since the
  existing local /24 route already covered reachability correctly
  (confirmed via `route-table ... detail`, `Suppressed: false`,
  successful FIB add on the /24).
- Delete+recommit of `arp evpn advertise dynamic` (the actual 7/24
  fix) -- retested on the theory that it was again stuck at its
  boot-time-only evaluation. Also had no effect.

Actual root cause: **the Linux server containers (srv1-4) had no
static route to the other tenant's subnet at all.** `topology.clab.yml`'s
per-server `exec` block was missing an `ip route add` line (e.g.
`ip route add 192.168.1.0/24 via 192.168.0.254 dev eth1` on srv1) --
servers had no way to reach the anycast gateway for cross-subnet
destinations regardless of leaf-side config correctness. 
Confirmed via `ip route` on all four containers (all missing
the cross-tenant route identically) and via `tcpdump -i e1-3` on
leaf1 showing zero ICMP traffic ever arriving from srv1 toward srv3,
despite every leaf-side control-plane check (ARP, EVPN Type-2,
route-table, IRB interface counters, ACLs, ip-forwarding options)
coming back clean. Lesson for future sessions: a uniformly-clean
control plane on every device in the path is itself a signal to
check the endpoints' own routing, not to re-verify device config a
second or third time.

Fix: added one `ip route add` line per server in `topology.clab.yml`'s
`exec` block, pointing each host at its local anycast gateway for the
other tenant's subnet. Verified cold: `containerlab destroy && deploy`,
full 12-pair matrix, run twice more after an initial single transient
failure (srv1->srv4 only, self-cleared on immediate retry, consistent
with first-boot EVPN convergence timing rather than a persistent
fault). Three consecutive clean runs across two full destroy/deploy
cycles. Phase 6 now meets the same cold-boot reproducibility bar as
Phases 4-5.

## Phase 7 -- intent-based deployment, verified 2026-07-29

automation/intent.yml declares leaves, spines, tenants, and fabric-level
values (AS number, ISIS area, L3 VNI/EVI) as the single source of truth.
Jinja2 templates render one startup-config JSON per device; render.py calls
template.render() once per leaf_id/spine_id (not a single render() looping
internally over all devices) -- mirrors topology.clab.yml's per-node model
and keeps each render call's output independently diffable against its own
reference file.

Interface-name translation: intent.yml deliberately keeps containerlab's
short form (e1-N) rather than SR Linux's native ethernet-1/N, since
intent.yml sits alongside topology.clab.yml in the same repo and shares its
vocabulary. Translation happens once, at render time, via a Jinja filter
(srl_ifname) -- avoids hand-duplicating both spellings in source data. Real
bug caught during template-vs-reference diffing: srl_ifname was registered
on the Jinja Environment but never actually invoked in the template body for
three of four interface-name emission points; the filter's presence in
env.filters doesn't apply it anywhere without an explicit `| srl_ifname` in
the template text itself.

Two distinct per-tenant index counters in intent.yml, easy to conflate:
access-interface subinterface suffix (ethernet-1/3.N) and vxlan1.N are
zero-based (loop position); irb0.N uses the tenant's own one-based
irb_subif_index field directly. Same tenant, two different counters, no
shared field.

vrf-l3 (the L3 VNI/EVI ip-vrf, shared across all tenants) is not part of
the per-tenant loop -- it's a static block following it, referencing both
tenants' IRB interfaces directly. Its own vxlan-interface index has no
backing field in intent.yml; derived in-template as `tenants | length + 1`
("one past the last tenant") rather than hardcoded, so it stays correct if
tenant count changes.

Confirmed (again, independently for spine after the earlier leaf-side
finding in Phase 6): srl_nokia-system:system (TLS/AAA/logging/gRPC/SNMP) and
the full ACL block are not required in a startup-config file for a working
cold-boot deploy. Spine1/spine2's startup-configs were hand-reduced to
interfaces + network-instance only and round-tripped live (containerlab
destroy/deploy, full cross-tenant matrix, 0% loss) before the template was
written against that reduced shape -- fact-finding preceded template design
rather than the reverse.

Incidental finding, not a Phase 7 defect: startup-configs/leaf2.json carried
a pre-existing `}`/`]` mismatch on the network-instance array's closing
token, likely introduced during an earlier manual reduction pass. Fixed in
this session's commit.

## Cold-boot reproducibility re-verified via genuine --cleanup, 2026-07-30

Prompted by a flash-persistence bug found in a separate lab
(arista-ceos-labs, same evening) -- Containerlab's `ceos` kind was
found to silently boot from stale per-node state after a plain
`destroy`, only a genuine `--cleanup` forces real re-seed from source
config. Raised the question of whether this repo's own Phase 4-6
"confirmed cold-boot reproducible" claims, all verified via plain
`destroy && deploy`, might have the same latent gap.

Re-tested: `containerlab destroy -t topology.clab.yml --cleanup`
(confirmed genuine removal -- deploy log showed "Creating lab
directory," proving no prior directory existed), followed by
`containerlab deploy -t topology.clab.yml`. Full 12-pair cross-tenant/
cross-leaf ping matrix plus 4 gateway checks (`full-cross` script):
16/16 passed, 0% loss, no transient failures at all -- cleaner than
the original Phase 6 verification, which had one self-clearing
single-pair miss on first boot.

Conclusion: this repo's cold-boot reproducibility claim was already
accurate under the stricter `--cleanup` standard, not merely under a
plain `destroy`. The `nokia_srlinux` kind does not appear to share the
`ceos` kind's flash-persistence behavior, or at minimum this specific
topology isn't exposed to it. Existing gap-analysis.md EVPN/VXLAN
Closeable classification stands, now with a stronger evidentiary basis
than it had before tonight.
