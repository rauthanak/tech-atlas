# Classify sample (plan 9, item 8)

Run `58ff24def8e2`: 50 of 50 technologies, status completed, 0 with a failed answer, 0 answers asked again alone.

## Tokens

- 50 calls (0 failed)
- 539,024 tokens sent, 372,152 of them reused (69%)
- 17,222 tokens written back
- per technology: about 10,780 sent and 344 written

## Agreement with Tata's labels

Technologies matching Tata's file exactly, with pages: 41.

- Domain: 36 of 41 (88%)
- Commercial availability: 19 of 41 (46%)
- TRL, exact: 3 of 11 (27%); within one level: 9 of 11 (82%)

| Technology | Tata: domain · availability · TRL | Classify: domain · availability · TRL | Evidence |
|---|---|---|---|
| 50G-PON | networking · early_commercial · 7 | networking · pilot · 6 | enough |
| 5G standalone | networking · early_commercial · 8 | networking · mature · 9 | strong |
| 5G-Advanced | networking · early_commercial · 7 | networking · early_commercial · 8 | strong |
| AI alignment | ai · research · — | ai · research · — | thin |
| AI governance | ai · early_commercial · — | ai · unclassified · — | thin |
| AI in robotics | ai · early_commercial · — | robotics · unclassified · — | thin |
| AI model compression | ai · early_commercial · — | ai · unclassified · — | thin |
| Agentic AI | ai · early_commercial · — | ai · early_commercial · 7 | enough |
| CBRS | networking · early_commercial · 8 | networking · pilot · 7 | thin |
| Carrier aggregation | networking · mature · 9 | networking · mature · — | thin |
| Computer vision | ai · mature · — | ai · early_commercial · 8 | enough |
| Continual learning | ai · research · — | ai · research · — | thin |
| Conversational AI | ai · mature · — | ai · early_commercial · 9 | thin |
| Explainable AI | ai · early_commercial · — | ai · research · 3 | thin |
| Federated learning | ai · early_commercial · — | ai · research · 3 | thin |
| Generative AI | ai · mature · — | ai · mature · 9 | strong |
| Generative design | ai · early_commercial · — | other · unclassified · — | thin |
| Graph neural networks | ai · early_commercial · — | ai · unclassified · — | not_credible |
| Large language models | ai · mature · — | ai · mature · 9 | strong |
| LoRa | ai · early_commercial · — | iot · early_commercial · 6 | enough |
| LoRaWAN | networking · mature · 9 | iot · unclassified · — | thin |
| Massive MIMO | networking · mature · 9 | networking · early_commercial · 9 | thin |
| Multimodal AI | ai · early_commercial · — | ai · early_commercial · 7 | enough |
| Network digital twin | networking · early_commercial · 7 | networking · research · — | thin |
| Network slicing | networking · early_commercial · 7 | networking · early_commercial · 9 | enough |
| Open RAN | networking · early_commercial · — | networking · early_commercial · 9 | enough |
| Private 5G | networking · early_commercial · 8 | networking · early_commercial · 8 | enough |
| Quantum computing | quantum · pilot · 3 | quantum · pilot · 5 | enough |
| Quantum key distribution | quantum · early_commercial · 8 | quantum · early_commercial · 7 | enough |
| Quantum memory | quantum · early_commercial · 4 | quantum · research · — | thin |
| Quantum networking | quantum · pilot · 4 | quantum · pilot · — | thin |
| Quantum sensing | quantum · early_commercial · 6 | quantum · research · — | thin |
| Reinforcement learning | robotics · early_commercial · 6 | ai · early_commercial · 7 | enough |
| Segment routing over IPv6 | networking · mature · — | networking · early_commercial · 8 | enough |
| Semantic communication | networking · research · 3 | networking · research · — | thin |
| Silicon photonics | networking · early_commercial · 8 | networking · early_commercial · — | thin |
| Sparse attention | ai · early_commercial · — | ai · research · 3 | thin |
| Speech recognition | ai · mature · 9 | ai · mature · 9 | enough |
| Spiking neural networks | ai · research · 5 | ai · unclassified · — | thin |
| World models | ai · early_commercial · — | ai · research · — | thin |
| diffusion models | ai · mature · — | ai · unclassified · — | thin |

## Reading the agreement

- **Commercial availability:** where Classify gave a value, it matches Tata in 19 of 33 (58%), and is within one step in 26 of 33 (79%). The other 8 answered "Unclassified": on thin evidence the skill abstains rather than guess, as it's told to. For technologies on Tata's list, the import makes Tata's own value a person's choice, which wins.
- **Domain:** 36 of 41 (88%). Most differences are reasonable alternatives (LoRa and LoRaWAN under IoT rather than AI or Networking; AI in robotics under Robotics).
- **TRL:** Tata gave a TRL for only 11 of these; 9 of 11 are within one level.

## Decision

Classify is switched on, after each collection. Its token budget per run is raised from 2,000,000 to 8,000,000 (counting reused tokens at a tenth, their price): the first pass over about 1,600 technologies needs about 7,000,000 at this sample's rate, and later runs only take technologies with new pages.
