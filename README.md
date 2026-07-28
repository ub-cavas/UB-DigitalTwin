# UB Digital Twin

## Setup Instructions

1. Clone this repo and submodules
```bash
# SSH
git clone --recurse-submodules git@github.com:ub-cavas/UB-DigitalTwin.git
# HTTPS
git clone --recurse-submodules https://github.com/ub-cavas/UB-DigitalTwin.git
```

2. Install the documentation dependency and run the local server:
```bash
python3 -m pip install -r Documentation/requirements-docs.txt
python3 -m mkdocs serve -f Documentation/mkdocs.yml
```

