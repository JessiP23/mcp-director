Authorization with the MCP server failed. You can check your credentials and permissions. If this persists, share this reference with support: "ofid_e9bea4df691ea156"



19:09:17
[info     ] oauth_authorize_start          correlation_sha256_prefix=487bcc09efdc846f http_request_id=01KR9MPE0XD08DPJ4AVJ4E3DJQ-ewr mcp_client_redirect_host=claude.ai oauth_idp_callback_url=https://mcp-director.fly.dev/oauth/idp-callback supabase_host=gnlktspxhdthoveoyucs.supabase.co supabase_server_pkce=True
19:09:18
[info     ] oauth_idp_callback_pending_hit correlation_sha256_prefix=487bcc09efdc846f http_request_id=01KR9MPEZSQAZAM7JCNTK6APKH-ewr oauth_code_sha256_prefix=dfdbe564c7350dad
19:09:18
2026-05-10 19:09:18,681 INFO httpx HTTP Request: POST https://gnlktspxhdthoveoyucs.supabase.co/auth/v1/token?grant_type=pkce "HTTP/1.1 200 OK"
19:09:18
[info     ] oauth_redirect_mcp_client      correlation_sha256_prefix=487bcc09efdc846f http_request_id=01KR9MPEZSQAZAM7JCNTK6APKH-ewr mcp_client_redirect_host=claude.ai
19:09:19
[info     ] oauth_token_issued             http_request_id=01KR9MPG2237HSS9ED52KC9BSD-ord mcp_token_sha256_prefix=d18ff82a7034c84a
19:09:24
[info     ] oauth_authorize_start          correlation_sha256_prefix=0610f78c9a58d051 http_request_id=01KR9MPMYBGS0E23AGSEP4TFJJ-ewr mcp_client_redirect_host=claude.ai oauth_idp_callback_url=https://mcp-director.fly.dev/oauth/idp-callback supabase_host=gnlktspxhdthoveoyucs.supabase.co supabase_server_pkce=True
19:09:25
[info     ] oauth_idp_callback_pending_hit correlation_sha256_prefix=0610f78c9a58d051 http_request_id=01KR9MPNM98P6NNZ5B0N7CB4GF-ewr oauth_code_sha256_prefix=f095b31ef66b14d1
19:09:25
2026-05-10 19:09:25,472 INFO httpx HTTP Request: POST https://gnlktspxhdthoveoyucs.supabase.co/auth/v1/token?grant_type=pkce "HTTP/1.1 200 OK"
19:09:25
[info     ] oauth_redirect_mcp_client      correlation_sha256_prefix=0610f78c9a58d051 http_request_id=01KR9MPNM98P6NNZ5B0N7CB4GF-ewr mcp_client_redirect_host=claude.ai
19:09:26
[info     ] oauth_token_issued             http_request_id=01KR9MPPHCC4YQF0JFBAGRKYCX-ord mcp_token_sha256_prefix=a29793e6f576ffe2
Machine	Checks	Region	


I am unable to connect my connector, why is that? is it the issue here in mcp director or in director cut? and how to fix it then? i have written a file showing the network logs eachon eof htem and the status as well, ensure otpo read the filea nd lmk how to fix it ok? 


307:
Request URL
https://claude.ai/api/organizations/dadd19e6-f0c5-45a2-b24a-5fd4b13bf3a1/mcp/start-auth/8600d6f8-ff26-415c-aa58-6891f0c33b90?redirect_url=%2Fsettings%2Fconnectors%3F&open_in_browser=1&product_surface=claude-web
Request Method
GET
Status Code
307 Temporary Redirect
Remote Address
[2607:6bc0::10]:443
Referrer Policy
strict-origin-when-cross-origin
alt-svc
h3=":443"; ma=86400
cf-cache-status
DYNAMIC
cf-ray
9f9b46182dbbb4c1-ORD
content-length
0
date
Sun, 10 May 2026 19:15:40 GMT
location
https://mcp-director.fly.dev/oauth/authorize?response_type=code&client_id=9cd751fe-2747-4b9b-a44b-46da086e5348&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback&code_challenge=gR0WqQkjcQJPBoSh1Jkgy55BO7gE8KkpFTuCcy_b7pE&code_challenge_method=S256&state=PNwKGxenwgAWyCsPKQHqrO5Eguc9z_gaR0ubqCV3XS8&scope=pipeline%3Aread+pipeline%3Awrite+assets%3Aread
priority
u=0,i
request-id
req_011CauRXYC5VC4FHzHfmeSMx
server
cloudflare
server-timing
cfExtPri
set-cookie
mcp_oauth_state_PNwKGxenwgAWyCsP=PNwKGxenwgAWyCsPKQHqrO5Eguc9z_gaR0ubqCV3XS8; Domain=claude.ai; HttpOnly; Max-Age=1800; Path=/; SameSite=lax; Secure
set-cookie
__cf_bm=KL33dkF7dveXJ3MRknzaADeR5wK4tVmGRqzRR694ofs-1778440538.9037123-1.0.1.1-0R4rSiK3aXt11dp9F1tdMPcRBpxmRwBuEaE88w0GvnEjk0RY.UpXgTc1FfSZg242J3mZMbUgSNkt2jTXFfhSnXM__MVu4heFE_6rVpltNKBdLRCZNj8206VmNUx29WLD; HttpOnly; Secure; Path=/; Domain=claude.ai; Expires=Sun, 10 May 2026 19:45:40 GMT
strict-transport-security
max-age=31536000; includeSubDomains; preload
x-envoy-upstream-service-time
1112
x-robots-tag
none
:authority
claude.ai
:method
GET
:path
/api/organizations/dadd19e6-f0c5-45a2-b24a-5fd4b13bf3a1/mcp/start-auth/8600d6f8-ff26-415c-aa58-6891f0c33b90?redirect_url=%2Fsettings%2Fconnectors%3F&open_in_browser=1&product_surface=claude-web
:scheme
https
accept
text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
accept-encoding
gzip, deflate, br, zstd
accept-language
en-US,en;q=0.9
cookie
_fbp=fb.1.1778403551878.94316871433754050; anthropic-device-id=0fb2e651-2186-4755-914c-2a13d62a1e70; activitySessionId=3ec753ff-15d4-4521-92e7-28cbff2188b9; ajs_anonymous_id=claudeai.v1.ec1efbc9-02b9-4676-81e9-a1658f882de2; CH-prefers-color-scheme=dark; __ssid=d9089bbe-f8a7-438b-9e49-574636d211d2; _gcl_au=1.1.1213004529.1778403555; g_state={"i_l":0,"i_ll":1778403556477,"i_e":{"enable_itp_optimization":0},"i_et":1778403556475}; sessionKey=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; sessionKeyLC=1778403560483; routingHint=sk-ant-rh-eyJ0eXAiOiAiSldUIiwgImFsZyI6ICJFUzI1NiIsICJraWQiOiAiN0MxcWFPRnhqdWxaUjRFQnNuNk1UeUZGNWdDV2JHbFpNVDR2RklrRFFpbyJ9.eyJzdWIiOiAiYmEwZmE3MDEtMzU2OC00MDZmLWJmZjMtOWY4MDA5NGMwMmEyIiwgImlhdCI6IDE3Nzg0MDM1NjAsICJpc3MiOiAiY2xhdWRlLWFpLXJvdXRpbmciLCAib25ib2FyZGluZ19jb21wbGV0ZSI6IHRydWUsICJwaG9uZV92ZXJpZmllZCI6IGZhbHNlLCAiYWdlX3ZlcmlmaWVkIjogdHJ1ZX0.UWhlIWM6ca_svNe2UZinPfH9zg4ulBsyfrVbBDtutWzggLGHduhzOg9yTrJxJt-uj8b0nkRVM2Yddbi-U_f5Xw; lastActiveOrg=dadd19e6-f0c5-45a2-b24a-5fd4b13bf3a1; user-sidebar-visible-on-load=true; intercom-device-id-lupk8zyo=79706bac-9b5b-4b71-adc1-74f480740887; user-sidebar-pinned=false; _cfuvid=Oi7yCx9EGDxO2SjT599F7bN0NkNBXMKiSD1y_CE4KAo-1778440100.1829247-1.0.1.1-_L9v2KduR9tcSTlXrdiobQPu.WHBFv60ePNTn0hSiD8; intercom-session-lupk8zyo=ci9wSVZCWHBSV2U2d0JoSThmQklGbmI0SU55WU5LbUpTWlJJOVp1TnVjbFFjdmNEbFZxQU1GeFlFUTdDQXlZcFovVy9ldE5wd004UnppSW9jMHErTWp2UTFibUx6TlpFS05tdWcxWDZ2eUkwdlZKK0NSaUZEait2czFZV0s3VU1yM0ZjTVdabkNqZ29iQ085RVhsejFpaFhiVzkzRWN1ZDVybjVHdi91T3A3N2hxU3VKSDlRNlE4Z0djY3M1SjFoWXV1N2dZekU3SG5jVUxhQ1duczU4TzhzYk1qSzNtbnJZeDBFZWtYS2J6VHVFVHFqZ3pRUHk1TmkvQmlDVDZTa3BiSGNNWXMwOGhFN1J4dzhnVlcyYmJzZ0wxbis3dU1VNGRnanJCY0g2bFk9LS1qNXRlMEFXc0JxM3pwQy9tK1pzRlR3PT0=--28cfe65d418faf1f498a7bf56d8437f48f5f3cd5; mcp_oauth_state_OBBr4u-v0WKIWZFo=OBBr4u-v0WKIWZFoysWODSuyJ4ddmAg1sohNyFzY7jE; mcp_oauth_state_tZUkpqjF0NQc2rT1=tZUkpqjF0NQc2rT1ArO5K4IhrFH5rVh44QqGL0q0t8I; mcp_oauth_state_QLC8olw0lSxmPKWt=QLC8olw0lSxmPKWtGrUUnlcYyQczjXthA5zAAZIdEis; mcp_oauth_state_1prpwYLjN0XvfNXg=1prpwYLjN0XvfNXg4XALkjYtDI03gIX9xbBLxl8oQ68; mcp_oauth_state_HNy62txJTFwoN-_z=HNy62txJTFwoN-_zxfUmEIdAlZaOP9ulX7jP_J3YK4k; cf_clearance=uEH8NCYL2jagbLQpi5mvRQsIVxV35YiLkn9Uxigrtcw-1778440166-1.2.1.1-eJkknaZAhaebwYkpPDDxri_JjH2mdKuLVSVo7y2Vs2zlQX6SYnr7hROmwHQPZC647BkI4n0QhgsN7_NFz_N6..ziD231LyrXy8drDIKqNiwvsI0VsSB2Arc1GeGBclL9.q95dYOFO0vvgnsG3i8upI75nGpnDHrd_tia5MSUd9KHZdJAoxBHeGD7lbCMXRDOnQJZTHzfvH5nGj_Qe333GZXLfh4L4naAyy3aQdhN8Hl7p9WtrMb2bejKTnFjcMJTwHf_gtlHpFiIgyMTjP3qnDYTS_vAu.kdWIQQc3kVOE02qkIgCqLrRzEIE2oihxELqL51P59UveUYH0e6B7vTKQ; __cf_bm=zYk02Spx2oJu64HWNgrVFYaMTm9Vez2DPVXaFfdCW4s-1778440166.954304-1.0.1.1-yx_TDCtgKb.V54rbO.PvMPELYxZBaFCsf9hFANq_o.rTmY00wZKLWfkmxtyiHKsbH1ARMudHcAWZHpccNtEViUolWzjQmt_iKRarT8KSDkIVF8kDgizjg9B9tP0xqOi_; _dd_s=aid=1c204229-8389-480e-96e9-66c7a0863670&rum=2&id=24dd4646-b49e-4287-98fc-3f5451e55060&created=1778440100121&expire=1778441438861
priority
u=0, i
referer
https://claude.ai/settings/connectors
sec-ch-ua
"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
sec-ch-ua-mobile
?0
sec-ch-ua-platform
"macOS"
sec-fetch-dest
document
sec-fetch-mode
navigate
sec-fetch-site
same-origin
sec-fetch-user
?1
upgrade-insecure-requests
1
user-agent
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36




Request URL
https://mcp-director.fly.dev/oauth/authorize?response_type=code&client_id=9cd751fe-2747-4b9b-a44b-46da086e5348&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback&code_challenge=gR0WqQkjcQJPBoSh1Jkgy55BO7gE8KkpFTuCcy_b7pE&code_challenge_method=S256&state=PNwKGxenwgAWyCsPKQHqrO5Eguc9z_gaR0ubqCV3XS8&scope=pipeline%3Aread+pipeline%3Awrite+assets%3Aread
Request Method
GET
Status Code
302 Found
Remote Address
[2a09:8280:1::112:933f:0]:443
Referrer Policy
strict-origin-when-cross-origin
content-length
0
date
Sun, 10 May 2026 19:15:39 GMT
fly-request-id
01KR9N23ZAEAYQM2SHAVWJ5TSY-ewr
location
https://gnlktspxhdthoveoyucs.supabase.co/auth/v1/authorize?provider=google&redirect_to=https%3A%2F%2Fmcp-director.fly.dev%2Foauth%2Fidp-callback%3Fmcp_oauth%3DdNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I&code_challenge=Ns9kQ91MZpLvZb37Pxd3uEC_V58dxgY8qm1T6YODsQk&code_challenge_method=S256
server
Fly/a589ac11 (2026-05-08)
via
2 fly.io
:authority
mcp-director.fly.dev
:method
GET
:path
/oauth/authorize?response_type=code&client_id=9cd751fe-2747-4b9b-a44b-46da086e5348&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback&code_challenge=gR0WqQkjcQJPBoSh1Jkgy55BO7gE8KkpFTuCcy_b7pE&code_challenge_method=S256&state=PNwKGxenwgAWyCsPKQHqrO5Eguc9z_gaR0ubqCV3XS8&scope=pipeline%3Aread+pipeline%3Awrite+assets%3Aread
:scheme
https
accept
text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
accept-encoding
gzip, deflate, br, zstd
accept-language
en-US,en;q=0.9
priority
u=0, i
referer
https://claude.ai/
sec-ch-ua
"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
sec-ch-ua-mobile
?0
sec-ch-ua-platform
"macOS"
sec-fetch-dest
document
sec-fetch-mode
navigate
sec-fetch-site
cross-site
sec-fetch-user
?1
upgrade-insecure-requests
1
user-agent
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36

{"detail":"unknown or expired state"}



Request URL
https://gnlktspxhdthoveoyucs.supabase.co/auth/v1/authorize?provider=google&redirect_to=https%3A%2F%2Fmcp-director.fly.dev%2Foauth%2Fidp-callback%3Fmcp_oauth%3DdNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I&code_challenge=Ns9kQ91MZpLvZb37Pxd3uEC_V58dxgY8qm1T6YODsQk&code_challenge_method=S256
Request Method
GET
Status Code
302 Found
Remote Address
172.64.149.246:443
Referrer Policy
strict-origin-when-cross-origin
alt-svc
h3=":443"; ma=86400
cf-cache-status
DYNAMIC
cf-ray
9f9b46209c747a9c-EWR
content-encoding
gzip
content-security-policy
default-src 'none'; sandbox
content-type
text/plain
date
Sun, 10 May 2026 19:15:40 GMT
location
https://accounts.google.com/o/oauth2/v2/auth?client_id=1022499821461-470n8bds63l7bce22b9gm024v3cgkqoa.apps.googleusercontent.com&redirect_to=https%3A%2F%2Fmcp-director.fly.dev%2Foauth%2Fidp-callback%3Fmcp_oauth%3DdNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I&redirect_uri=https%3A%2F%2Fgnlktspxhdthoveoyucs.supabase.co%2Fauth%2Fv1%2Fcallback&response_type=code&scope=email+profile&state=4471dcd4-a318-487b-9b94-004a0e69a3f0
priority
u=0,i
sb-gateway-version
1
sb-project-ref
gnlktspxhdthoveoyucs
sb-request-id
019e1351-1069-7011-bd9c-30d26a4800f1
server
cloudflare
server-timing
cfExtPri
set-cookie
__cf_bm=2YNsJa_3W1NbrFnZFFmGx.ZKTaI1pMpBKOLPfAa0vFM-1778440540.2595947-1.0.1.1-uTRBPxT2Szmfql7TQJYoq3PSsBpv8OWucdjtStrDwEHMF.ldzqH_i2ibC.P0MmyCWVXxYh.C4rmKbm6sAhg4rrCPKNn4OWUq4jlCwbWDBD_0jYe1j8qZfRq.PGoAQ5SP; HttpOnly; Secure; Path=/; Domain=supabase.co; Expires=Sun, 10 May 2026 19:45:40 GMT
strict-transport-security
max-age=31536000; includeSubDomains; preload
vary
Origin, Accept-Encoding
x-content-type-options
nosniff
x-envoy-attempt-count
1
x-envoy-upstream-service-time
7
:authority
gnlktspxhdthoveoyucs.supabase.co
:method
GET
:path
/auth/v1/authorize?provider=google&redirect_to=https%3A%2F%2Fmcp-director.fly.dev%2Foauth%2Fidp-callback%3Fmcp_oauth%3DdNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I&code_challenge=Ns9kQ91MZpLvZb37Pxd3uEC_V58dxgY8qm1T6YODsQk&code_challenge_method=S256
:scheme
https
accept
text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
accept-encoding
gzip, deflate, br, zstd
accept-language
en-US,en;q=0.9
priority
u=0, i
referer
https://claude.ai/
sec-ch-ua
"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
sec-ch-ua-mobile
?0
sec-ch-ua-platform
"macOS"
sec-fetch-dest
document
sec-fetch-mode
navigate
sec-fetch-site
cross-site
sec-fetch-user
?1
upgrade-insecure-requests
1
user-agent
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36

Request URL
https://accounts.google.com/o/oauth2/v2/auth?client_id=1022499821461-470n8bds63l7bce22b9gm024v3cgkqoa.apps.googleusercontent.com&redirect_to=https%3A%2F%2Fmcp-director.fly.dev%2Foauth%2Fidp-callback%3Fmcp_oauth%3DdNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I&redirect_uri=https%3A%2F%2Fgnlktspxhdthoveoyucs.supabase.co%2Fauth%2Fv1%2Fcallback&response_type=code&scope=email+profile&state=4471dcd4-a318-487b-9b94-004a0e69a3f0
Request Method
GET
Status Code
302 Found
Remote Address
64.233.180.84:443
Referrer Policy
strict-origin-when-cross-origin
alt-svc
h3=":443"; ma=2592000,h3-29=":443"; ma=2592000
cache-control
no-cache, no-store, max-age=0, must-revalidate
content-encoding
gzip
content-length
428
content-security-policy
require-trusted-types-for 'script';report-uri /cspreport
content-security-policy
script-src 'report-sample' 'nonce-aNOnYAyJTaMTcwfBAMpl_g' 'unsafe-inline' 'unsafe-eval';object-src 'none';base-uri 'self';report-uri /cspreport
content-type
text/html; charset=UTF-8
cross-origin-opener-policy-report-only
same-origin; report-to="coop_gse_qebhlk"
date
Sun, 10 May 2026 19:15:40 GMT
expires
Mon, 01 Jan 1990 00:00:00 GMT
federation-rp-connection-status
status="connected", account_id="102130706905479464423"
location
https://gnlktspxhdthoveoyucs.supabase.co/auth/v1/callback?state=4471dcd4-a318-487b-9b94-004a0e69a3f0&iss=https%3A%2F%2Faccounts.google.com&code=4%2F0AeoWuM-2GyHBL-eLhyOUG_-avrpBls7mSPQqJKSm2dP0xxfcvMnzTkE4DWTAidh0NnoA8g&scope=email+profile+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile+openid&authuser=0&prompt=none
origin-trial
Ajo6ZZxoPufZZ6x0UgjawhB/adBJ+tLG7aX1MO8kWVCTHdOVSlY4OjhBhzivzulNh6ikNKRnwxwK18EvUu6aOgcAAABteyJvcmlnaW4iOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb206NDQzIiwiZmVhdHVyZSI6IldlYlZpZXdYUmVxdWVzdGVkV2l0aERlcHJlY2F0aW9uIiwiZXhwaXJ5IjoxNzU4MDY3MTk5fQ==
pragma
no-cache
report-to
{"group":"coop_gse_qebhlk","max_age":2592000,"endpoints":[{"url":"https://csp.withgoogle.com/csp/report-to/gse_qebhlk"}]}
server
GSE
strict-transport-security
max-age=31536000; includeSubDomains
x-content-type-options
nosniff
x-frame-options
DENY
x-xss-protection
1; mode=block
:authority
accounts.google.com
:method
GET
:path
/o/oauth2/v2/auth?client_id=1022499821461-470n8bds63l7bce22b9gm024v3cgkqoa.apps.googleusercontent.com&redirect_to=https%3A%2F%2Fmcp-director.fly.dev%2Foauth%2Fidp-callback%3Fmcp_oauth%3DdNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I&redirect_uri=https%3A%2F%2Fgnlktspxhdthoveoyucs.supabase.co%2Fauth%2Fv1%2Fcallback&response_type=code&scope=email+profile&state=4471dcd4-a318-487b-9b94-004a0e69a3f0
:scheme
https
accept
text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
accept-encoding
gzip, deflate, br, zstd
accept-language
en-US,en;q=0.9
cookie
ACCOUNT_CHOOSER=AFx_qI5mP4-lXmANgzxpSFllHvR6rs1SSCCKxsS4SbnOGeqa8Z4D3QaJsVEvaAskBPyIUg2Rii2tVQbjpKrfx-YhBEiNJHhTaOPnrHMY4eN2BQGLPaYF66qLdpzdCYnk6OvPS6KdZcbK; HSID=AMmJCgfbEZ7aPrhp7; SSID=AnDOUNHU7EuGl-CIT; APISID=pGpbOpFivd2b3F9N/AxNiNFSKWMq1_ksf_; SAPISID=lx0dAYOWggdffVDo/AO74DSeoNxpCLpj94; __Secure-1PAPISID=lx0dAYOWggdffVDo/AO74DSeoNxpCLpj94; __Secure-3PAPISID=lx0dAYOWggdffVDo/AO74DSeoNxpCLpj94; LSID=o.mail.google.com|s.youtube:g.a0004Airyy8f2kidnpZSJaEIury03C_PBCrutjtu-R383AFJ0ZzVM-4Wuz3Zx5ikUnvLSoktBwACgYKAZMSARISFQHGX2Mi9Zjk7sfn-31py0kzi_BtrBoVAUF8yKqcEfUfUEy9m_hgFBtjWWTd0076; __Host-1PLSID=o.mail.google.com|s.youtube:g.a0004Airyy8f2kidnpZSJaEIury03C_PBCrutjtu-R383AFJ0ZzV6McEaO__D_JZPiW63hCxiAACgYKAfESARISFQHGX2MimMPgGVycWnJsnDMZFm8tURoVAUF8yKroqVhlQCqwYUVM8nTj8ycM0076; __Host-3PLSID=o.mail.google.com|s.youtube:g.a0004Airyy8f2kidnpZSJaEIury03C_PBCrutjtu-R383AFJ0ZzVjBmhpyBhz5SIIPLi9eLkbgACgYKAQsSARISFQHGX2MimDk6aoCcqKJp9C7kh04I2BoVAUF8yKqPpAwDFJ6UJ3e2Poqchdxm0076; __Secure-BUCKET=CO4B; __Secure-1PSIDTS=sidts-CjIBBj1CYsJ02ULWN9cotlZ8anA9jjQCKFtsTvE7Wu8L-0P7zHlrIB6wVCLgDC3SFIbM5RAA; __Secure-3PSIDTS=sidts-CjIBBj1CYsJ02ULWN9cotlZ8anA9jjQCKFtsTvE7Wu8L-0P7zHlrIB6wVCLgDC3SFIbM5RAA; SID=g.a0009Airyw2x6o0SEbEQ8bdRys0tI7CSFLe7TklsrwoJNvejR99k7ZoOAxaxYKNAb-zyAUZ-5AACgYKAdUSARISFQHGX2MinViyzLD2hSX22QY37UAwJhoVAUF8yKqRE19wbclwFtUS1745JSao0076; __Secure-1PSID=g.a0009Airyw2x6o0SEbEQ8bdRys0tI7CSFLe7TklsrwoJNvejR99k4sWR97nD8BcZqGPGVXPKYQACgYKAWISARISFQHGX2MiX_R2eB1QNBmQC-6EKn2zahoVAUF8yKqCrwN-VPdsEzkqbSYvEXNl0076; __Secure-3PSID=g.a0009Airyw2x6o0SEbEQ8bdRys0tI7CSFLe7TklsrwoJNvejR99k3gXe7LxOSQq2pXBEG3zuDgACgYKATcSARISFQHGX2Miq-CPG-jzlEhaXlRhALtoARoVAUF8yKoninnlfJ2v15wvAyzoaYxW0076; AEC=AaJma5u-4Jbgp2WpwCt9MayslZzpbIZ3xKIcNNZxTM_HNAZh-TRYvJMNpvs; __Host-GAPS=1:eu10bq_xPUjmF5vsc0zgPMehcqQYgKEPdrpJtbyv6bAz-FkUAeYGC_spIamubKzKl1jICy-jHxCgQ8EcczZ8CxNR24eX:TmOCHBmJbTnSrEbe; NID=531=cTmkQZuQn2WA2FCqILyQW4ZDUw80rMghyM0PU-vuRpxL_QIHS3GfrI7c2g03uhVHP2SP0FiqcMWdhj7PZUHc_r38JGFeUIV-vwryMStFev4wqCphfsaAV1Nk1V55138suNw9ftLxTdMuj55ASt-wN-mdTkxJuWSFv5gVQGtmVsXOxZtmaO8QzT793Oql7m4anTQi4nBEtCf5IuY3bv18aZIi500y2RTAEnF0yqHsOkue2DdJx4O_GESNSJkHTLvN8-GKj_s01oNblj7SlsilIhCycCRPgwy2R2gCtY3Zk21ulRUh1qECeI30Jc40CubZ0I9_G1SL-a5JiFfVgoIPQwFjxKHRs8U318Fk3QTuZEm-xYNLXWhp62gu7owmjlIcKz_uMJN_fQxDo2w16rJWIeYFxHJBZma5aRfoL5AbBq6IZwmKPxtMUjPLyzs5dv8ktW8Cf6QCed3N2kuih783GaRwS3MQcAUnBvJUfU-NFPyfk6peT7dJR_ZtZ2LpSz4JPdQ3zbWOkzXu62DrjjpEdTwOXiTc9EEk-vn0IF1XOSiEmEKPuyQ_i5Prr2UYui3mkIXm3Tpk8EwA8MnRSjqpy0HynZo3SOtW8hetI90i4ZBOdEP87VpodFen9SJNr69xFUmQib2L8YPwmmyri8LwILC2ZX3NZFHdutCgeVcltdwEssvRG3jzPQbDqWgDFB4qEaQ_HHz53A8fV-B99ccw5yLa8HWiP_LGfHldEn8XsM2ttP0hOMQr8rAs; SIDCC=AKEyXzUw6odW9IExKe2q88yoEFF2Xvj7GrEXDZQi8S5S5gYLhNKq_QwsJtsP8_oYk80ra_S3D36e; __Secure-1PSIDCC=AKEyXzWmkiEhmXy_RFa3AaA3ONe3xq3fwbph7vSKPTdm1Pc8V8XjX-z8i8iGGATZUQkbTqoBkOw; __Secure-3PSIDCC=AKEyXzVzKVq3A_42lb6sfBAcZKLtsh0x04W5P2XRf6lYWUEWceZA9qEaGVOxCjVvFUiGX1tT3UQ
priority
u=0, i
referer
https://claude.ai/
sec-ch-ua
"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
sec-ch-ua-arch
"arm"
sec-ch-ua-bitness
"64"
sec-ch-ua-form-factors
"Desktop"
sec-ch-ua-full-version
"148.0.7778.96"
sec-ch-ua-full-version-list
"Chromium";v="148.0.7778.96", "Google Chrome";v="148.0.7778.96", "Not/A)Brand";v="99.0.0.0"
sec-ch-ua-mobile
?0
sec-ch-ua-model
""
sec-ch-ua-platform
"macOS"
sec-ch-ua-platform-version
"26.3.0"
sec-ch-ua-wow64
?0
sec-fetch-dest
document
sec-fetch-mode
navigate
sec-fetch-site
cross-site
sec-fetch-user
?1
upgrade-insecure-requests
1
user-agent
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36
x-browser-channel
stable
x-browser-copyright
Copyright 2026 Google LLC. All Rights Reserved.
x-browser-validation
UIi7qZu87K168QdaJpJ7m6oeku0=
x-browser-year
2026
x-chrome-id-consistency-request
version=1,client_id=77185425430.apps.googleusercontent.com,device_id=861c76af-8568-4f21-a79b-137ef1e878d4,signin_mode=all_accounts,signout_mode=show_confirmation


Request URL
https://gnlktspxhdthoveoyucs.supabase.co/auth/v1/callback?state=4471dcd4-a318-487b-9b94-004a0e69a3f0&iss=https%3A%2F%2Faccounts.google.com&code=4%2F0AeoWuM-2GyHBL-eLhyOUG_-avrpBls7mSPQqJKSm2dP0xxfcvMnzTkE4DWTAidh0NnoA8g&scope=email+profile+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile+openid&authuser=0&prompt=none
Request Method
GET
Status Code
302 Found
Remote Address
172.64.149.246:443
Referrer Policy
strict-origin-when-cross-origin
alt-svc
h3=":443"; ma=86400
cf-cache-status
DYNAMIC
cf-ray
9f9b46239b8b7a9c-EWR
content-encoding
gzip
content-security-policy
default-src 'none'; sandbox
content-type
text/plain
date
Sun, 10 May 2026 19:15:40 GMT
location
https://mcp-director.fly.dev/oauth/idp-callback?code=ceee1fcb-3bfd-4039-a3b3-65b25de6ef37&mcp_oauth=dNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I
priority
u=0,i
sb-gateway-version
1
sb-project-ref
gnlktspxhdthoveoyucs
sb-request-id
019e1351-1248-73c5-b1d7-3e2ecb0836be
server
cloudflare
server-timing
cfExtPri
set-cookie
__cf_bm=druAQyA7h7J6dLODVmKjE9ZMiwP2p6KDekTXqFTlm78-1778440540.739633-1.0.1.1-KzoOFbfZcMd1B0uNKyo0zxp.ioJxOSqgWYHkPFLt05_YyyNoBQW0TEDSU9tUOhPaQF84QQ_sHcF.pwfEcX.bcQ.W8xxlTqBNBWMp0DKAD6.djM6xo349nUTffV75Vin0; HttpOnly; Secure; Path=/; Domain=supabase.co; Expires=Sun, 10 May 2026 19:45:40 GMT
strict-transport-security
max-age=31536000; includeSubDomains; preload
vary
Origin, Accept-Encoding
x-content-type-options
nosniff
x-envoy-attempt-count
1
x-envoy-upstream-service-time
105
:authority
gnlktspxhdthoveoyucs.supabase.co
:method
GET
:path
/auth/v1/callback?state=4471dcd4-a318-487b-9b94-004a0e69a3f0&iss=https%3A%2F%2Faccounts.google.com&code=4%2F0AeoWuM-2GyHBL-eLhyOUG_-avrpBls7mSPQqJKSm2dP0xxfcvMnzTkE4DWTAidh0NnoA8g&scope=email+profile+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile+openid&authuser=0&prompt=none
:scheme
https
accept
text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
accept-encoding
gzip, deflate, br, zstd
accept-language
en-US,en;q=0.9
priority
u=0, i
referer
https://claude.ai/
sec-ch-ua
"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
sec-ch-ua-mobile
?0
sec-ch-ua-platform
"macOS"
sec-fetch-dest
document
sec-fetch-mode
navigate
sec-fetch-site
cross-site
sec-fetch-user
?1
upgrade-insecure-requests
1
user-agent
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36


Request URL
https://mcp-director.fly.dev/oauth/idp-callback?code=ceee1fcb-3bfd-4039-a3b3-65b25de6ef37&mcp_oauth=dNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I
Request Method
GET
Status Code
302 Found
Remote Address
[2a09:8280:1::112:933f:0]:443
Referrer Policy
strict-origin-when-cross-origin
content-length
0
date
Sun, 10 May 2026 19:15:40 GMT
fly-request-id
01KR9N24S8WG0C177VT1RH7KQ4-ewr
location
https://claude.ai/api/mcp/auth_callback?code=U_ByYt8ePpMcmP2n38sxa6zsH4CxSxCjDFvIf3dIYEQ3r0CEI3Pgw4Cw5f-tB1nW&state=PNwKGxenwgAWyCsPKQHqrO5Eguc9z_gaR0ubqCV3XS8
server
Fly/a589ac11 (2026-05-08)
via
2 fly.io
:authority
mcp-director.fly.dev
:method
GET
:path
/oauth/idp-callback?code=ceee1fcb-3bfd-4039-a3b3-65b25de6ef37&mcp_oauth=dNnFEuk0m6w4cA7pr2CuY--WKOShOlWO6MrGFm9eG2I
:scheme
https
accept
text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
accept-encoding
gzip, deflate, br, zstd
accept-language
en-US,en;q=0.9
priority
u=0, i
referer
https://claude.ai/
sec-ch-ua
"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
sec-ch-ua-mobile
?0
sec-ch-ua-platform
"macOS"
sec-fetch-dest
document
sec-fetch-mode
navigate
sec-fetch-site
cross-site
sec-fetch-user
?1
upgrade-insecure-requests
1
user-agent
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36