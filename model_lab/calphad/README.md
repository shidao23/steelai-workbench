# CALPHAD database (T86) — how to obtain the vendor database locally

The Workbench **does not redistribute** any thermodynamic database. The `databases/` directory in
this folder is Git-ignored and must stay out of the public repository, because the database carries
its own licence that is independent of the Workbench's MIT licence and of pycalphad's MIT licence.

## 1. Database in use

| item | value |
| --- | --- |
| database | MatCalc `mc_fe`, version **2.062** |
| publisher | MatCalc / TU Wien Institute of Materials Science and Technology (IMST) |
| assessed by | Erwin Povoden-Karadeniz and Aurélie Jacob |
| file date | 2024-11-08 |
| size | 489,296 bytes |
| SHA-256 | `aa02077eac3f602dd7479cbeafb09b450e282716752b3ae2b1fc3a57d9c64865` |
| licence | **ODbL 1.0 + DbCL 1.0** (stated on the vendor page *and* in the file header) |

## 2. Obtain it (official source only)

```powershell
# Official TU Wien / MatCalc release location (do not use mirrors or third-party copies)
$url = 'https://www.matcalc.at/images/stories/Download/Database/mc_fe_v2062.tdb'
New-Item -ItemType Directory -Force -Path model_lab\calphad\databases | Out-Null
Invoke-WebRequest -Uri $url -OutFile model_lab\calphad\databases\mc_fe_v2062.tdb -UseBasicParsing

# Verify the hash before registering it
(Get-FileHash model_lab\calphad\databases\mc_fe_v2062.tdb -Algorithm SHA256).Hash.ToLower()
```

Landing page: <https://www.matcalc.at/index.php/databases/open-databases>

Then register it locally by copying `config/calphad_tdb.example.json` to
`config/calphad_tdb.local.json` (git-ignored) and filling in the fields. The registration must
include the `pycalphad_compatibility` verdict; the adapter refuses to compute while that status is
not `passed`.

## 3. Licence obligations (ODbL 1.0 + DbCL 1.0)

- Free of charge, commercial use permitted (`ODbL §3.1`).
- If you **redistribute or commit** the database file, ship the licence URI and keep the notices
  intact, and any **derivative database** must itself be ODbL (`§4.2`, `§4.4`) with the derivative
  or an alteration file offered publicly (`§4.6`). This is one more reason the file is not committed here.
- Published **results** (a "Produced Work") are not a derivative database (`§4.5(b)`) but need an
  attribution notice (`§4.3`), for example:
  > Contains information from mc_fe v2.062 (MatCalc / TU Wien), which is made available here under
  > the Open Database License (ODbL).

## 4. Current status (2026-09-25, T86 phase 3)

### 4.1 The vendor original cannot be parsed

1. `Database(path)` → `UnicodeDecodeError: 'gbk' codec can't decode byte 0x96 in position 485974`
   (pycalphad opens the file with the platform locale encoding; the vendor file is cp1252).
2. With the encoding supplied (the file bytes are untouched) →
   `pyparsing.exceptions.ParseException: Invalid TDB syntax` at **line 180, column 18**, on the
   MatCalc-only command `REFERENCE_ELEMENT FE`.

The original is kept only for provenance and for the diff audit, and is **not selectable**. Evidence:
`docs/T86_PHASE2_ENVIRONMENT_AND_GATES.md` and `config/calphad_gate_evidence_v1.0.json`.

### 4.2 Community derivative candidate (phase 3)

Per the project owner's decision, the raw vendor file is **not** preprocessed here. Instead a
third-party community compatibility derivative is registered
(`MATCALC-MC-FE-V2062-COMMUNITY-CLEAN-19B1164`), placed in the git-ignored
`model_lab/calphad/databases/community/` directory:

| Item | Value |
| --- | --- |
| Repository | `adityamoolya/maraging-steel-calphad-dft` (publishes **no LICENSE file**; no code copied) |
| File and commit | `2databases/mc_fe_v2062_clean.tdb` @ `19b11640253543fe412145498438cb8355a32561` |
| Size / SHA-256 | 479,418 bytes / `7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042` |
| Licence | Upstream **ODbL 1.0 + DbCL 1.0** preserved in the file header (lines 26-29) |
| Local handling | Not modified, not committed, not redistributed; SteelAI produced no derived TDB |

It must be described **only** as a third-party community derivative database candidate — never as a
TU Wien official pycalphad-compatible build, a pycalphad official database, or a validated SteelAI
database.

### 4.3 Blocking limit in this environment

pycalphad 0.11.2 here cannot solve an equilibrium whose component list is longer than **13** entries
(Fe + 11 alloying elements + VA); **14** either exhausts memory or aborts natively inside
`pycalphad/core/minimizer`. The identical 13/14 boundary reproduces on pycalphad's own bundled
`COST507.tdb`, so it is an environment limitation, not a defect of this database. Both project heats
need 16 component entries, so no phase-fraction curve can be produced for a real sample and **T86
remains `Blocked`**; the database candidate is recorded as `compatibility_candidate`.

Full evidence, validation results and reproduction commands:
`docs/T86_PHASE4_REDUCED_SYSTEM.md`, `docs/T86_PHASE3_COMMUNITY_COMPATIBILITY.md` and
`config/calphad_gate_evidence_v1.1.json`.

### 4.4 Phase 4: fixed reduced component system and fixed phase range

The project owner approved a **fixed** `steel_matrix_equilibrium_v1` component profile (12 elements
plus the `VA` vacancy, i.e. 13 component-list entries — the measured capacity bound on this host) and
a **fixed** `steel_matrix_major_carbides_v1` phase range (`LIQUID, FCC_A1, BCC_A2, CEMENTITE,
M23C6, M7C3, M6C`, all seven independently verified). No environment change and no pycalphad
upgrade were made, and the full 16-component system is not attempted. There is **no generic element
or phase switch**: a mismatched component set blocks with `CALPHAD-COMP-012`, a missing phase with
`CALPHAD-PHASE-001`, and a real-sample run without a named approval with `CALPHAD-COMP-011` (the code
never fills in a reviewer name).

Ten-step validation: steps 1–5 and 9 pass; R-DQ converges at all 54 points; **B-DQ does not converge
at 875 °C in the batch scan**, so step 6 fails and **T86 remains `Blocked`** — never
`pilot_ready_pending_scientific_review`. A defect was also found and fixed here: omitting `VA` from
the pycalphad component list returns a physically wrong assemblage while the phase-fraction sum still
equals 1, so the worker now always adds it and the validation checks physical plausibility.

Evidence: `config/calphad_reduced_system_v1.0.json`, `config/calphad_phase_profile_evidence_v1.0.json`,
`config/calphad_phase4_evidence_v1.0.json`.

### 4.5 Phase 5: one fresh process per temperature point

The formal solver mode is now `independent_single_point_process_v1`: every temperature point runs in
its own worker process, exactly one temperature per process, strictly serial, with no warm start and
identical inputs except temperature. The phase-4 batch warm-start path is demoted to
`diagnostic_only`. Each point records a full contract (request hash, worker PID and exit code, `VA`
presence, database SHA-256, solve status, active phases, phase-fraction sum, runtime, sanitized
stderr, first-attempt flag, solver mode) and the run carries a point manifest plus an integrity hash;
a missing point yields no partial curve, and a diagnostic retry never becomes part of the formal
result.

The acceptance is still **blocked**: near 875 °C and 900 °C the single-point solve itself is
non-deterministic in fresh processes (B-DQ 900 °C succeeded 1/8 times), so **T86 remains `Blocked`**
and the batch-versus-independent question is settled — the failure is not caused by warm-starting.

Evidence: `config/calphad_phase5_evidence_v1.0.json` and
`docs/T86_PHASE5_INDEPENDENT_POINTS.md`.
