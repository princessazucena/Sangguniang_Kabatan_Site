# Scholarship Portal

A small Flask + Tailwind CSS + Supabase app where students upload scholarship
documents and admins verify them. Announcements and sign-up / log-in live on
the public area.

## Stack
- Python 3.11+ / Flask
- Tailwind CSS via CDN
- Supabase (Auth + Postgres + Storage)

## Project layout
```
SK/
├── app.py                   # Flask entry point
├── supabase_client.py       # Supabase client wrapper
├── routes/
│   ├── public.py            # /home, /login, /signup, /logout
│   ├── student.py           # /student/dashboard, /student/upload
│   └── admin.py             # /admin/dashboard, /admin/review, /admin/announcements
├── templates/
│   ├── base.html
│   ├── public/              # home, login, signup
│   ├── student/             # dashboard
│   └── admin/               # dashboard, review, announcements
├── static/
│   ├── css/app.css
│   └── img/background.jpg   # add your hero image here
├── schema.sql               # run this in Supabase SQL editor
├── requirements.txt
└── .env                     # SUPABASE_URL + SUPABASE_SECRET_KEY
```

## One-time setup

1. **Set up Supabase**
   - Open your Supabase project, go to *SQL editor*, paste the contents of
     `schema.sql`, and run it. This creates the tables, the
     `scholarship-files` storage bucket, and basic RLS policies.
   - Copy your project URL (e.g. `https://xxxx.supabase.co`) and put it in
     `.env` as `SUPABASE_URL`.
   - The secret key is already in `.env` — rotate it if it leaked.

2. **Create an admin user**
   - Sign up through the website with the email you want to use as admin.
   - In the Supabase *Table editor* open `public.profiles`, find that user,
     and change their `role` from `student` to `admin`.

3. **Add a background image**
   - Save a hero image as `static/img/background.jpg`.

## Run locally

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

## Notes
- The Flask backend uses the Supabase **secret** key, which bypasses RLS.
  Never ship that key to the browser.
- File uploads are capped at 16 MB (`MAX_CONTENT_LENGTH` in `app.py`).
- Admins see signed URLs that expire after 30 minutes.
