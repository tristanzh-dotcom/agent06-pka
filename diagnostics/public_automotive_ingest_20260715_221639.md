# PKA Public Automotive Ingest Verification

- status: passed
- started_at: 2026-07-16T06:15:25+08:00
- finished_at: 2026-07-16T06:16:39+08:00
- runtime_root: removed (isolated /tmp runtime)

## Sample evidence

| sample | SHA-256 | upload | quality | coverage | chunks | recall | duplicate | delete/re-upload |
|---|---|---|---|---|---:|---|---|---|
| automotive_docx_exclusion |  |  |  |  | 0 | fts=False; vector=0 | False | deleted=False; reuploaded=False |
| automotive_pptx_exclusion |  |  |  |  | 0 | fts=False; vector=0 | False | deleted=False; reuploaded=False |
| ons_vehicle_registrations_xlsx | 3ecc8bc12c115e15e836814fceb9b3e85ba628931dcaa266122a85c51b7c2c47 | ok |  | complete | 101 | fts=True; vector=10 | True | deleted=True; reuploaded=True |
  - provenance: https://www.ons.gov.uk/file?uri=%2Feconomy%2Feconomicoutputandproductivity%2Foutput%2Fdatasets%2Fuknewvehicleregistrationsandproduction%2F2026%2Fsmmtvehicleregandproddataset090726.xlsx
| nhtsa_automotive_pdf | ceb19d7b2d990223506451ce9243ba8c0e14ac6ece85075fcf564155bfe41815 | ok | high | complete | 4 | fts=True; vector=3 | True | deleted=True; reuploaded=True |
  - provenance: https://static.nhtsa.gov/odi/tsbs/2024/MC-10249194-0001.pdf
| apollo_autonomous_vehicle_png | 8ceb7a9ea49131cbba31e76cbfad8eb9536d7b378046208f748d58631bf5e276 | ok | high | complete | 3 | fts=True; vector=3 | True | deleted=True; reuploaded=True |
  - provenance: https://raw.githubusercontent.com/ApolloAuto/apollo/master/cyber/docs/images/cyber_monitor.png
| nuscenes_can_bus_markdown | 5dc8055180339dc68b6e7b7f9b479b762e4313ccf4ff94429103f40464b369d3 | ok |  | complete | 11 | fts=True; vector=8 | True | deleted=True; reuploaded=True |
  - provenance: https://raw.githubusercontent.com/nutonomy/nuscenes-devkit/refs/heads/master/python-sdk/nuscenes/can_bus/README.md
| apollo_canbus_txt | b53e38779ca7a3ddbe53763b983f30008a54d76fa2ec1d5c4ede2d100ec7133b | ok |  | complete | 3 | fts=True; vector=1 | True | deleted=True; reuploaded=True |
  - provenance: https://raw.githubusercontent.com/ApolloAuto/apollo/master/modules/canbus/conf/canbus_conf.pb.txt

## Failures

- none
