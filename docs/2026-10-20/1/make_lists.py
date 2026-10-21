"""Builds the seeded classification and value lists (plan 9, items 8 and 12)
from Tata's "Emerging-technologies October 2026.xlsx" and Nick's value-levers
note, once; the seed files are then checked by hand and edited in the portal.

    .venv/bin/python docs/2026-10-20/1/make_lists.py path/to/tata.xlsx

Writes seeds/availability.json, domains.json, subdomains.json,
trl_levels.json, path_steps.json, mechanisms.json, and adds the levers, key
metrics, blockers, cautions and finance defaults to seeds/fabrics.json."""

import json
import re
import sys
from pathlib import Path

import openpyxl

SEEDS = Path(__file__).resolve().parents[3] / "seeds"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def write(name: str, items: list[dict]) -> None:
    (SEEDS / f"{name}.json").write_text(json.dumps({name: items}, indent=2, ensure_ascii=False) + "\n")
    print(f"seeds/{name}.json: {len(items)}")


AVAILABILITY = [
    ("research", "Research", "In labs and papers: no product anyone can buy yet.", True),
    ("pilot", "Pilot", "Trials or pilots with named customers or partners, but not generally sold.", True),
    ("early_commercial", "Early commercial", "First products on sale and early customers; the market is still forming.", True),
    ("mature", "Mature", "Sold by several vendors to many customers, in an established market.", False),
]

DOMAINS = [  # Tata's nine, the three blockchain spellings merged into one
    ("ai", "AI", "Artificial intelligence: models, agents, and the tools to build and run them.", ["AI"]),
    ("cloud", "Cloud", "Cloud platforms, services and the way they are run.", ["Cloud"]),
    ("cybersecurity", "Cybersecurity", "Protecting networks, systems, data and identities.", ["Cybersecurity"]),
    ("edge_computing", "Edge Computing", "Computing close to where data is made, outside central clouds.", ["Edge Computing"]),
    ("iot", "IoT", "Connected devices and sensors, and the networks and platforms that serve them.", ["IoT"]),
    ("networking", "Networking", "Networks and the technologies that carry, manage and secure traffic.", ["Networking"]),
    ("quantum", "Quantum", "Quantum computing, communication and sensing, and quantum-safe security.", ["Quantum"]),
    ("robotics", "Robotics and Autonomous Systems", "Robots, drones and autonomous machines.", ["Robotics and Autonomous Systems"]),
    ("blockchain_web3", "Blockchain/Web3", "Distributed ledgers, digital assets and decentralised applications.",
     ["Blockchain/Web3", "Blockchain", "Blockchain/Cybersecurity"]),
]

TRL = [
    (1, "Basic principles observed", "Scientific research has begun; the principles are reported, not yet applied."),
    (2, "Concept formulated", "A practical use is proposed, but nothing has been built to prove it."),
    (3, "Proof of concept in the lab", "Experiments show the key functions work, in a lab."),
    (4, "Validated in the lab", "Components work together in a lab setting."),
    (5, "Validated in a relevant setting", "Components tested in conditions close to real use."),
    (6, "A prototype shown in a real setting", "A working prototype demonstrated in a relevant, realistic setting."),
    (7, "A full prototype working in operation", "A near-final system demonstrated in real operation."),
    (8, "Complete and qualified", "The final system is built and passes its tests and qualification."),
    (9, "Proven in operation", "The system is in successful real-world use."),
]

PATH = [  # Tri's seven steps, with Nick's evidence on the steps that match his ladder
    ("evaluation", "Evaluation", "A named lever and a plausible chain from the technology to its financial effect.",
     "Monitor; assign a fabric owner."),
    ("customer_zero", "Customer zero", "Measured cost per outcome against the current process, including running costs, "
     "when Tata uses the capability internally.", "Fund a proof of concept."),
    ("proof_of_concept", "Proof of concept", "A named buyer, a budget or willingness to pay and an indicative price; for "
     "protection levers, the exposed contracts and their renewal dates.", "Seek a first customer."),
    ("one_customer", "One customer", "Positive contribution after fully loaded delivery costs, and a payback estimate.",
     "Commit business-unit investment and scale."),
    ("beta", "Beta", "For Tata to define.", "For Tata to define."),
    ("roadmap", "Roadmap", "For Tata to define.", "For Tata to define."),
    ("investment", "Investment", "For Tata to define.", "For Tata to define."),
]

MECHANISMS = [
    ("protect", "Protect existing contribution", "Keep contribution Tata already earns, such as a contract renewed "
     "because the technology meets a requirement."),
    ("earn", "Earn additional contribution", "New paid use, new customers or a higher price, net of what it displaces."),
    ("reduce_cost", "Reduce the cost of an equivalent outcome", "Deliver the same outcome, at comparable quality, "
     "for less, counting implementation, integration, monitoring, exceptions and support."),
    ("less_capital", "Serve demand with less capital", "Meet the same demand with less new investment, such as "
     "higher utilisation of what Tata owns."),
]

LEVERS = {  # Nick's table: lever 1 (contribution), lever 2 (delivery cost), key metrics, blockers to test
    "network": ("protect", "Contract contribution protected or won where stronger security or a required performance "
                "level qualifies Tata for a renewal or new contract",
                "Lower cost per delivered service through automated provisioning, assurance or transport",
                "Engineering hours per connection; incidents per service; cost per comparable traffic unit",
                "Compatibility with the installed network and vendors; customer qualification and procurement"),
    "cloud": ("earn", "Contribution from paid workloads or managed services, measured on actual paid use rather than "
              "reserved capacity",
              "Lower cost per comparable workload; where Tata owns infrastructure, higher utilisation that avoids new "
              "investment",
              "Paid utilisation; margin after infrastructure, licences and support",
              "Migration and data integration; access to capacity and a proposition customers will pay for"),
    "security": ("earn", "Contribution from paid security adoption, sold new or attached to network and cloud contracts",
                 "Lower analyst effort per effectively resolved case",
                 "Attach rate; incremental price; cost per resolved case; false-positive and escalation rates",
                 "Integration and telemetry quality; demonstrable effectiveness; specialist delivery capacity"),
    "interaction": ("earn", "Contribution from paid adoption or expansion, net of any billable minutes or seats the "
                    "automation removes",
                    "Lower cost per successfully resolved task, including carrier, model, cloud, escalation and "
                    "repeat-contact costs",
                    "Resolution rate; repeat contacts; fully loaded cost per resolved task",
                    "Reliable task completion in real workflows; integration effort; pricing that covers ongoing costs"),
    "iot": ("earn", "Contribution from activated, paying devices rather than devices shipped or registered",
            "Lower lifecycle servicing cost through remote provisioning, diagnosis and updates",
            "Active paying devices; paid lifetime; field visits avoided where Tata bears the cost",
            "Device and network interoperability; enterprise rollout across the device lifecycle"),
    "media": ("earn", "Contribution from paid events or customers, with no assumed price premium",
              "Lower cost per comparable event through remote production or reusable infrastructure",
              "Contract value; cost per event at comparable reliability and latency",
              "Reliability under peak event demand; integration with customer and partner production workflows"),
}
CAUTIONS = {
    "security": "A customer's avoided breach loss isn't Tata revenue: count it only through a fee, more demand or "
                "retention.",
    "interaction": "Automation can remove billable minutes or seats Tata already earns on: net that displacement off "
                   "any gain.",
}


def main(xlsx: str) -> None:
    write("availability", [{"availability_id": i, "name": n, "definition": d, "order": k + 1, "emerging": e,
                            "catch_all": False} for k, (i, n, d, e) in enumerate(AVAILABILITY)]
          + [{"availability_id": "unclassified", "name": "Unclassified",
              "definition": "The pages don't show how available it is yet.", "order": 99, "emerging": False,
              "catch_all": True}])
    write("domains", [{"domain_id": i, "name": n, "definition": d, "order": k + 1, "catch_all": False}
                      for k, (i, n, d, _) in enumerate(DOMAINS)]
          + [{"domain_id": "other", "name": "Other", "definition": "Fits none of the domains above.", "order": 99,
              "catch_all": True}])
    by_spelling = {s: i for i, _, _, spellings in DOMAINS for s in spellings}
    sheet = openpyxl.load_workbook(xlsx, read_only=True)["New Emerging Technologies"]
    rows = list(sheet.iter_rows(values_only=True))
    head = [str(h or "").strip() for h in rows[0]]
    d_col, s_col = head.index("Domain"), head.index("Sub-domain")
    subs: dict[str, dict] = {}
    for r in rows[1:]:
        domain, sub = (str(r[d_col] or "").strip(), str(r[s_col] or "").strip())
        if not sub or domain not in by_spelling:
            continue
        sid = f"{by_spelling[domain]}--{slug(sub)}"
        subs.setdefault(sid, {"subdomain_id": sid, "name": sub, "domain_id": by_spelling[domain], "status": "seeded"})
    write("subdomains", sorted(subs.values(), key=lambda s: (s["domain_id"], s["name"].lower())))
    write("trl_levels", [{"trl_id": str(n), "level": n, "name": name, "definition": d} for n, name, d in TRL])
    write("path_steps", [{"step_id": i, "name": n, "order": k + 1, "evidence_needed": e, "decision": dec}
                         for k, (i, n, e, dec) in enumerate(PATH)])
    write("mechanisms", [{"mechanism_id": i, "name": n, "definition": d} for i, n, d in MECHANISMS])

    path = SEEDS / "fabrics.json"
    data = json.loads(path.read_text())
    for f in data["fabrics"]:
        mech1, l1, l2, metrics, blockers = LEVERS[f["fabric_id"]]
        f["levers"] = [{"lever_id": f"{f['fabric_id']}_contribution", "name": "Contribution", "mechanism_id": mech1,
                        "text": l1},
                       {"lever_id": f"{f['fabric_id']}_delivery_cost", "name": "Delivery cost",
                        "mechanism_id": "reduce_cost", "text": l2}]
        f["key_metrics"] = metrics
        f["bottlenecks"] = [b.strip() for b in blockers.split(";")]
        f["cautions"] = CAUTIONS.get(f["fabric_id"], "")
        f["finance_defaults"] = {"margin_low": None, "margin_high": None, "loss_without": None, "loss_with": None}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("seeds/fabrics.json: levers, key metrics, bottlenecks, cautions, finance defaults")


if __name__ == "__main__":
    main(sys.argv[1])
