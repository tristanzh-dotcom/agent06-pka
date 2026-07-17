# PKA Public Automotive Ingest Verification

- status: failed
- started_at: 2026-07-16T06:09:01+08:00
- finished_at: 2026-07-16T06:09:31+08:00
- runtime_root: /var/folders/by/ryk2x0p133n0q7syh20tp2l40000gn/T/pka-public-automotive-ingest-waal4f9m

## Sample evidence

| sample | SHA-256 | upload | quality | coverage | chunks | recall | duplicate | delete/re-upload |
|---|---|---|---|---|---:|---|---|---|
| ons_vehicle_registrations_xlsx | 3ecc8bc12c115e15e836814fceb9b3e85ba628931dcaa266122a85c51b7c2c47 | ok |  | complete | 101 | fts=True; vector=True | True | deleted=True; reuploaded=True |
  - provenance: https://www.ons.gov.uk/file?uri=%2Feconomy%2Feconomicoutputandproductivity%2Foutput%2Fdatasets%2Fuknewvehicleregistrationsandproduction%2F2026%2Fsmmtvehicleregandproddataset090726.xlsx
| nhtsa_automotive_pdf | ceb19d7b2d990223506451ce9243ba8c0e14ac6ece85075fcf564155bfe41815 | ok | high | complete | 4 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://static.nhtsa.gov/odi/tsbs/2024/MC-10249194-0001.pdf
| nuscenes_can_bus_markdown | 5dc8055180339dc68b6e7b7f9b479b762e4313ccf4ff94429103f40464b369d3 | ok |  | complete | 11 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://raw.githubusercontent.com/nutonomy/nuscenes-devkit/refs/heads/master/python-sdk/nuscenes/can_bus/README.md
| openpilot_vehicle_models_txt | 676b95e380b6f1d0d70bce3b7dbecd6bfb84c20bd789af4edc4d9e6ca0407d8e | ok |  | complete | 1 | fts=False; vector=False | False | deleted=False; reuploaded=False |
  - provenance: https://raw.githubusercontent.com/commaai/openpilot/master/openpilot/selfdrive/car/tests/test_models_segs.txt

## Failures

- nhtsa_automotive_pdf: 'NoneType' object is not subscriptable
- nuscenes_can_bus_markdown: 'NoneType' object is not subscriptable
- openpilot_vehicle_models_txt: 'NoneType' object is not subscriptable
