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
