# Google Indexing API Setup Guide
## MeeeShop SEO Automation — One-Time Setup

This guide gets you from zero to automated daily indexing in ~15 minutes.

---

## What This Does

After setup, every time `blog_daily.yml` publishes a new blog post,
the `google_indexing.yml` workflow automatically fires and tells Google
to crawl that URL immediately. Without this, Google might take 2–8 weeks
to discover a new blog post.

---

## Step 1: Enable the Indexing API in Google Cloud

1. Go to: https://console.cloud.google.com/apis/library/indexing.googleapis.com
2. Make sure your **meeeshop project** is selected in the top dropdown
3. Click **ENABLE** (if not already enabled)

✅ Done when you see "API enabled"

---

## Step 2: Create a Service Account

1. Go to: https://console.cloud.google.com/iam-admin/serviceaccounts
2. Click **+ CREATE SERVICE ACCOUNT**
3. Fill in:
   - **Name:** `meeeshop-indexing`
   - **ID:** (auto-generated, leave it)
   - **Description:** `Shopify blog & product indexing automation`
4. Click **Create and Continue**
5. Skip the role assignment → click **Continue** → click **Done**

---

## Step 3: Download the JSON Key

1. In the service accounts list, click on `meeeshop-indexing@...`
2. Click the **Keys** tab
3. Click **Add Key** → **Create new key**
4. Select **JSON** → click **Create**
5. A `.json` file downloads automatically — **keep it safe, don't commit it!**

> [!CAUTION]
> The downloaded JSON file contains your private key. Anyone with it can
> index URLs on your behalf. Store it securely and delete the local copy
> after adding it to GitHub Secrets.

---

## Step 4: Add Service Account to Google Search Console

This is the critical step — without it, the API returns 403 errors.

### Method A: URL-Prefix Property (Most Reliable)

> [!IMPORTANT]
> If your GSC property is a **Domain property** (shows `sc-domain:` prefix),
> use Method A below — domain properties block service account emails from
> the normal "Add User" flow.

1. Go to https://search.google.com/search-console/
2. Click the property dropdown → **Add property**
3. Choose **URL prefix** (right side) → enter `https://us.meeeshop.com/`
4. Click **Continue** (will auto-verify since domain is already verified)
5. In the new URL-prefix property → **Settings** → **Users and permissions**
6. Click **Add user** → paste the `client_email` from your JSON key file
   - It looks like: `meeeshop-indexing@your-project.iam.gserviceaccount.com`
7. Set permission to **Owner** → click **Add**

✅ Done when you see the service account email listed as Owner

### Method B: Try Domain Property First

If your GSC property is already a URL-prefix property, just:
1. Go to your property → **Settings** → **Users and permissions**
2. Click **Add user** → paste the `client_email` → set to **Owner** → **Add**

> [!WARNING]
> Permission MUST be **Owner** (not Full or Restricted).
> The Indexing API requires Owner-level access or it returns 403.

---

## Step 5: Add GitHub Secret

1. Open the downloaded `.json` file in a text editor (Notepad, VS Code, etc.)
2. Select ALL the content (Ctrl+A) and copy it
3. Go to your GitHub repo: https://github.com/meeeshop/meeeshop-seo/settings/secrets/actions
4. Click **New repository secret**
5. Fill in:
   - **Name:** `GOOGLE_SA_KEY_JSON`
   - **Value:** paste the entire JSON content
6. Click **Add secret**

> [!TIP]
> The JSON will look like a single blob of text with `private_key`, `client_email`,
> etc. Paste it exactly as-is — no formatting needed.

✅ Done when `GOOGLE_SA_KEY_JSON` appears in your secrets list

---

## Step 6: Test It

### Dry Run (safe — no API calls)

1. Go to your repo → **Actions** tab → **Google Indexing API** workflow
2. Click **Run workflow** → set:
   - Days: `3`
   - Dry run: `true`
3. Click **Run workflow**
4. Watch the logs — you should see URLs printed without any API calls

### Live Run (real indexing)

1. Same as above but set **Dry run: `false`**
2. You should see output like:
   ```
   [  1/  3] ✓ OK  https://us.meeeshop.com/blogs/fashion/your-blog-post
   [  2/  3] ✓ OK  https://us.meeeshop.com/blogs/style/another-post
   ```

### What 403 Means

If you see `403 PERMISSION DENIED`, the service account isn't added as
Owner in Search Console yet. Re-do Step 4.

### What 429 Means

Google's free quota is 200 URLs/day. If you hit this, the script stops
early and logs which URLs weren't submitted. Just run again tomorrow.

---

## How It Runs Automatically

The workflow runs on two triggers:

1. **After blog_daily.yml** — automatically fires when blog posts are published
   (chain trigger via `workflow_run`)

2. **Daily cron** — runs 30 minutes after each blog schedule:
   - Tuesday 8:30 AM EST
   - Thursday 8:30 AM EST
   - Saturday 9:30 AM EST

---

## Quota & Limits

| Limit | Value |
|-------|-------|
| Daily quota (free) | 200 URLs/day |
| Per-request delay | 0.15 seconds |
| Max URLs per run (default) | 200 |

Your blog posts per day: 1–3 (well within quota)
If you run `--products`, add ~100 product URLs. Still under 200.

---

## Verify It Worked

After a live run, verify indexing in Google Search Console:

1. Go to https://search.google.com/search-console/
2. Click **URL Inspection** (left sidebar)
3. Paste one of the submitted blog URLs
4. Click **Request Indexing** — if it says "URL is on Google", it worked!
5. Or check **Coverage** → **Valid** for new URLs appearing

Google typically crawls submitted URLs within 1–48 hours.

---

## Files Created

| File | Purpose |
|------|---------|
| `scripts/google_indexing.py` | Main indexing script |
| `.github/workflows/google_indexing.yml` | GitHub Actions automation |
| `GOOGLE_INDEXING_SETUP.md` | This setup guide |

The secret `google_sa_key.json` is in `.gitignore` — never committed.
