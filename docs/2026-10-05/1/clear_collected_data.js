// Plan 7: clear the collected data from Docker's tech_atlas. Every setting stays.
// Run inside the Docker mongo container, never against localhost:27017 from the Mac (that is the brew MongoDB):
//   docker exec tech-radar-mongo-1 mongosh --quiet tech_atlas --eval "$(cat clear_collected_data.js)"
// Undo: mongorestore --archive=replaced/db-before-plan7.archive.gz --gzip --drop (inside the same container).
const collected = ["runs", "documents", "technologies", "resolves", "scoring_runs",
                   "assessments", "povs", "pov_compose_jobs", "recheck_jobs"];
if (db.getName() !== "tech_atlas") throw new Error("wrong database: " + db.getName());
for (const c of collected) print(c.padEnd(17), "deleted", db.getCollection(c).deleteMany({}).deletedCount);
// saved searches and job-board counts keep their reading progress on the source itself
const reset = db.sources.updateMany({ access: "query", progress: { $exists: true } }, { $unset: { progress: "" } });
print("progress reset on", reset.modifiedCount, "data sources");
for (const c of db.getCollectionNames().sort()) print(c.padEnd(17), db.getCollection(c).countDocuments({}));
