# WynnGuessr

play it here : **https://wynndle.com**

this is a fork of [Ched3's WynnGuessr](https://github.com/Ched3/Wynnguessr). the original was a really cool idea, GeoGuessr but in Wynncraft, but it hasn't been updated in a while and the map changed a lot since. so i took it and started making an updated and better version of it with my friends.

big thanks to Ched3 (Edison Chen) for making the original, none of this would exist without it !

## what's different

we redid basically everything location-wise. the map is the 2026 one now, and all the old photos got replaced by new 360° panoramas we took ourselves with a small Fabric mod (no hud, no players, no name tags, just the world). there's over 600 spots right now, from Wynn to Gavel, Corkus, the Ocean and the Silent Expanse. Fruma is coming once i've got photos for it.

the photos are also way sharper than before, you can actually zoom in and see stuff.

and there's multiplayer now !! you make a room, send the code to your friends and play together. in rooms you have Classic, Duel and Battle Royale, and solo you have Classic and Survival.

also : you can log in with your Wynncraft account, there's leaderboards for Classic and Survival, your friends can join rooms as guests without making an account, and it works on phone.

## running it yourself

it's a Flask app :

```bash
git clone https://github.com/Yasu-ro/Wynnguessr.git
cd Wynnguessr
pip install -r requirements.txt
flask run
```

then go on http://127.0.0.1:5000. the new photos aren't in the repo (way too big), so locally you'll only get the old ones from the original.

## contact

if you find a bug or a spot that's broken, open an issue !

it's a fan project, not affiliated with Wynncraft.
