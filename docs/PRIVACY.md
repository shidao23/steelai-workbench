# Privacy and Publication Boundary

## Never committed

- raw OM/SEM/EBSD/XRD files;
- CTF, TIF, Zarr, model weights and instrument exports;
- local absolute paths and machine-specific settings;
- real processed research tables;
- API keys, secrets or provider responses containing sensitive context;
- thesis text, unpublished reports, company/client material or personal records.

## Public demo controls

- synthetic data only;
- external AI disabled;
- evidence-path registration disabled;
- processed-data upload disabled;
- MATLAB/MTEX and GPU launch paths unconfigured;
- GitHub CI uses synthetic fixtures and requires no API key.

## External AI contract

Private deployments may send only de-identified processed structured values and analysis summaries. Raw images, CTF/TIF files, file paths and full documents are outside the allowed payload.

## Incident response

If a secret or confidential file is ever committed, stop deployment, rotate the credential if applicable, remove it from the full Git history and review forks/caches before resuming publication.
