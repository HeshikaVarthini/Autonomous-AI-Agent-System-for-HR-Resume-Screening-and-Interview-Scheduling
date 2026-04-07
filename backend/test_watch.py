"""
test_watch.py
=============
Run this to test the form watcher directly.
No FastAPI needed. Just Python.

Usage:
    python test_watch.py
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(__file__))


async def my_callback(response, resume_bytes, resume_filename, job_id):
    print("\n" + "="*50)
    print("NEW RESPONSE RECEIVED")
    print(f"  Name     : {response['name']}")
    print(f"  Email    : {response['email']}")
    print(f"  Phone    : {response['phone']}")
    print(f"  LinkedIn : {response['linkedin']}")
    print(f"  Row #    : {response['row_number']}")

    if resume_bytes:
        os.makedirs("downloads", exist_ok=True)
        path = f"downloads/{resume_filename}"
        with open(path, "wb") as f:
            f.write(resume_bytes)
        print(f"  Resume   : SAVED → {path} ({len(resume_bytes)//1024} KB)")
    else:
        print(f"  Resume   : NOT FOUND")
    print("="*50)


async def main():
    from form_watcher import FormWatcher, get_google_creds

    print("\n GOOGLE FORM AUTO-WATCHER TEST")
    print("="*50)

    url = input("\nPaste your Google Form URL:\n> ").strip()
    if not url:
        print("No URL. Exit.")
        return

    print("\nChecking Google credentials...")
    try:
        get_google_creds()
        print("Authenticated OK")
    except FileNotFoundError as e:
        print(str(e))
        return

    w = FormWatcher(
        form_url   = url,
        job_id     = "test_job",
        on_new_response = my_callback,
        poll_every = 30,
    )

    print("\nSetting up...")
    try:
        info = await w.setup()
    except ValueError as e:
        print(f"\nERROR: {e}")
        return

    print(f"\n  Form      : {info['form_title']}")
    print(f"  Sheet URL : {info['sheet_url']}")
    print(f"  Existing  : {info['existing_responses']} responses (will be skipped)")
    print(f"\n  Detected columns:")
    for field, col_name in info["columns_detected"].items():
        print(f"    {field:12} → '{col_name}'")

    print(f"\n Watching for NEW submissions every 30s")
    print(" Submit your form now ...")
    print(" Ctrl+C to stop\n")

    try:
        await w.start()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    asyncio.run(main())
