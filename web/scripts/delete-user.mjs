// Development tool: delete one account (and its history and notifications) from the local database.
//   npm run delete:user -- someone@example.com
// The audit journals on the Python side are NOT touched: the journal is append-only by design.
import Database from "better-sqlite3";
import fs from "node:fs";

const email = (process.argv[2] ?? "").trim().toLowerCase();
if (!email) { console.log("Usage: npm run delete:user -- someone@example.com"); process.exit(1); }
const file = process.env.DATABASE_PATH ?? "./data/askboard.db";
if (!fs.existsSync(file)) { console.log(`No database at ${file}`); process.exit(1); }

const db = new Database(file);
db.pragma("foreign_keys = ON");                       // so the user's analyses and notifications go too
const user = db.prepare("SELECT id, email, provider FROM users WHERE email = ? COLLATE NOCASE").get(email);
if (!user) { console.log(`No account with ${email}.`); process.exit(0); }
const n = db.prepare("SELECT (SELECT COUNT(*) FROM analyses WHERE user_id = ?) AS a, (SELECT COUNT(*) FROM notifications WHERE user_id = ?) AS n")
  .get(user.id, user.id);
db.prepare("DELETE FROM users WHERE id = ?").run(user.id);
console.log(`Deleted ${user.email} (${user.provider} account), ${n.a} analyses and ${n.n} notifications.`);
console.log("Sign out in the browser (or clear the site's cookies) before creating the account again.");
