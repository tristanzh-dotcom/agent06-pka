# PKA Public Automotive Ingest Verification

- status: failed
- started_at: 2026-07-16T00:47:46+08:00
- finished_at: 2026-07-16T00:47:56+08:00
- runtime_root: removed (isolated /tmp runtime)

## Sample evidence

| sample | SHA-256 | upload | quality | coverage | chunks | recall | duplicate | delete/re-upload |
|---|---|---|---|---|---:|---|---|---|
| unece_r154_docx |  |  |  |  | 0 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://wiki.unece.org/download/attachments/265978083/Base%20Document%20for%20R154_04_200625.docx?api=v2
| unece_eve_pptx |  |  |  |  | 0 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://unece.org/sites/default/files/2025-03/GRPE-92-49r1e.pptx
| ons_vehicle_registrations_xlsx | 3ecc8bc12c115e15e836814fceb9b3e85ba628931dcaa266122a85c51b7c2c47 |  |  |  | 0 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://www.ons.gov.uk/file?uri=%2Feconomy%2Feconomicoutputandproductivity%2Foutput%2Fdatasets%2Fuknewvehicleregistrationsandproduction%2F2026%2Fsmmtvehicleregandproddataset090726.xlsx
| nhtsa_tire_safety_pdf |  |  |  |  | 0 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://www.nhtsa.gov/sites/nhtsa.gov/files/2021-11/Tires_InTheGarage_Infographic_102621_v1_-eng-tag.pdf
| nhtsa_blind_spot_png |  |  |  |  | 0 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://www.nhtsa.gov/sites/nhtsa.gov/files/styles/large/public/lane_changing-blindspotdetection.png?itok=ZA5351jD
| nuscenes_can_bus_markdown | 5dc8055180339dc68b6e7b7f9b479b762e4313ccf4ff94429103f40464b369d3 | ok |  | complete | 11 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://raw.githubusercontent.com/nutonomy/nuscenes-devkit/refs/heads/master/python-sdk/nuscenes/can_bus/README.md
| public_automotive_txt_exclusion |  |  |  |  | 0 | fts=False; vector=False | False | deleted=False; reuploaded=False |

## Failures

- unece_r154_docx: HTTP Error 403: Forbidden
- unece_eve_pptx: HTTP Error 403: Forbidden
- ons_vehicle_registrations_xlsx: Client error '413 Request Entity Too Large' for url 'http://127.0.0.1:50386/api/ingest/file'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/413
- nhtsa_tire_safety_pdf: HTTP Error 403: Forbidden
- nhtsa_blind_spot_png: HTTP Error 403: Forbidden
- nuscenes_can_bus_markdown: No module named 'engine'
