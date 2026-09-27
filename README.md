# NextTrack

NextTrack recommends songs based on the tracks in a user's playlist. It uses Deezer for track searches and short previews, Last.fm for similar tracks and tags, and MusicBrainz for track information.

## Setup

1. Create and activate a Python virtual environment.
2. Install the packages:

   pip install -r requirements.txt

3. Create a file named `.env` beside `app.py` and add:

   LASTFM_API_KEY=your_key_here

4. Start the application:

   python app.py

5. Open http://127.0.0.1:8000 in your browser.

## Tests

Run the tests from the project folder:

   python -m unittest test_app.py