"""What a seeding-data load would change on this database: for every seeded
list, items it would add, remove, or whose seeded fields it would overwrite.
Run inside the atlas container: docker exec -i tech-radar-atlas-1 python - < this"""
from app.services.db import seeding
from app.services.db.mongo import get_collection
total = 0
for name, id_field in seeding.ID_FIELDS.items():
    items = seeding.read_list(name)
    fields = [f for f in seeding.list_fields(items) if f not in seeding.NOT_COMPARED]
    live = {d["_id"]: d for d in get_collection(name).find()}
    seeds = {i[id_field]: i for i in items}
    added = sorted(set(seeds) - set(live))
    removed = sorted(set(live) - set(seeds))
    changed = {k: [f for f in fields if f != id_field and seeds[k].get(f) != live[k].get(f)]
               for k in seeds if k in live}
    changed = {k: v for k, v in changed.items() if v}
    total += len(added) + len(removed) + len(changed)
    print(f"{name:15} live {len(live):4} seeds {len(seeds):4} | add {added} | remove {removed} | overwrite {changed}")
print("ITEMS A LOAD WOULD CHANGE:", total)
st = get_collection("seeding").find_one({"_id": "state"}) or {}
print("loaded_at", st.get("loaded_at"), "| fingerprint matches files:", st.get("fingerprint") == seeding.fingerprint())
