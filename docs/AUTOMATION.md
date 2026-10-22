# Two sides, one engine

The same engine feeds two businesses:

1. **Gifts (Etsy and our own shop):** personalised packs for one named child, made to order.
2. **YouTube (sleep and relaxation channel):** long, calm videos made in batches, which send viewers to the shop.

## Story videos that show the story

Narration timing drives the pictures. While the voice is generated we record when each paragraph starts and ends, and each story paragraph carries a scene tag. The video cuts or dissolves between illustrated scenes exactly as the narrator reaches each moment.

| Story moment | Scene |
|---|---|
| Settling in, breathing | Dim bedroom, arched window onto their real birth-night sky, nightlight glow |
| The star at the window | The star brightens and blinks twice, as if waving |
| The starlight companion | Their favourite animal fades in on the sill as a glowing silhouette full of sparkles |
| The moonbeam ride | A silver ribbon lifts them past rooftops and clouds into the night |
| The planets | The real planets from their birth night drift past: Jupiter's bands, Saturn's rings, rusty Mars |
| Arriving at their nebula | The deep zoom into their own nebula, in their favourite colour |
| The wishes | One small star floats down for each wish, timed to each sentence |
| The message | The giver's words appear softly in gold |
| Home and the countdown | The ride home, then stars go out one by one, ten to one |
| Goodnight | Back at the window; the companion curls up and fades; the star bursts into their name |

`skysoftly/scenes.py` already draws the bedroom window, the planets and six companion animals (bunny, fox, cat and bear read well; owl and elephant need another pass). Prototype frames: `docs/listing/story-scenes-prototype.jpg` and `docs/listing/starlight-animals.jpg`.

For YouTube, the same scenes play with a made-up character (for example "Luna"), never a customer's child.

## Automating gift delivery

### Route A: Etsy, almost automatic

Etsy's API lets a program read new orders and the buyer's personalisation text, but it cannot send buyer messages or attach files to a made-to-order item. So one short manual step remains.

1. A worker script checks Etsy for new paid orders every few minutes (Etsy Open API v3: shop receipts and their transactions, which hold the personalisation text).
2. It reads the answers from the personalisation box. The listing asks for them in a fixed numbered format so the parser is reliable.
3. It builds the pack, uploads it to a Google Drive folder, and makes a share link.
4. It emails you: "Isla's pack is ready, here's the preview and the link."
5. You spend about a minute: listen to the name, upload the files to the Etsy order, paste the video link, mark it complete.

Etsy's shop setting for a message sent with every digital sale can carry fixed instructions such as "your pack arrives within 24 hours".

### Route B: our own shop, fully automatic

1. A one-page shop on Netlify with an order form and Stripe Checkout (both free to start; Stripe takes a fee per sale).
2. Stripe calls a small Netlify function when payment succeeds. It stores the order in a Supabase table.
3. The render worker picks up the order, builds the pack, uploads it to Supabase Storage, and creates a download link that expires after 30 days.
4. The customer gets an email with the link and a preview. If they spot a problem with the name, a reply goes to you.

Run both: Etsy for discovery and trust, our own shop for repeat buyers and higher margins.

### The render worker

- **Free option:** your own computer, left on overnight, running a loop that picks up orders. A modern 8-core computer renders a video about twice as fast as this 4-core test machine.
- **Paid option:** a cloud server with more cores, roughly the cost of a few orders a month. No graphics card is needed.
- Packs without video take about 4 minutes, so those can go out within the hour. Videos run in a queue.

## Automating the YouTube side

1. **Batch rendering:** each week, one command renders the next week's "Tonight's Sky" episodes plus one long sleep video.
2. **Uploading:** the YouTube Data API uploads each video with its title, description, tags and thumbnail, and schedules when it goes public. Uploads use a large share of the daily API quota, so a few a day is the practical limit.
3. **Every description** links to the shop and says the narration is a synthetic voice.
4. **Never** upload a customer's personalised video without their written permission.

## What we need from you to switch it on

| For | What |
|---|---|
| Etsy route | An Etsy developer app and API key, and permission for it to read your shop's orders |
| Own shop | A Stripe account, a Netlify site and a Supabase project; these tools are already connected to this workspace |
| Delivery links | A Google Drive folder or Supabase Storage |
| YouTube | A channel and a Google Cloud project with the YouTube Data API enabled |
| Worker | A computer that can stay on, or a small cloud server |

Keys stay on your machine or in the hosting settings, never in this repository.
