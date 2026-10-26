# Atlas for Office

Word and Excel desktop task pane add-in. It reads the active selection only after the user clicks **发送选区到当前 Atlas 会话**. Atlas opens the paired conversation with the selection as a local draft; nothing is sent to a model until the user reviews and sends that draft. Text sent back by `/office writeback <文本>` appears in the task pane and is inserted into the current Office selection only after **写入当前选区** is clicked.

## Start and sideload

1. Start Atlas Desktop and open the conversation that should receive Office selections.
2. In that conversation, run `/office` and copy the 8 digit pairing code.
3. Install [mkcert](https://github.com/FiloSottile/mkcert), then from this directory run `mkcert -install` and `mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost 127.0.0.1 ::1`. These two local files are ignored by Git. Run `npm install` and `npm start`; keep the HTTPS server running at `https://localhost:3000`.
4. In Word or Excel desktop, open **Insert → Add-ins → My Add-ins → Upload My Add-in**, then choose `manifest.xml` in this directory. Open **Atlas for Office** from the add-ins menu.
5. Enter the 8 digit pairing code in the task pane. The code expires after five minutes, accepts at most five guesses, and works once. The add-in keeps its session token in that Office profile's local storage; it is never added to an Atlas prompt or log.

## Use

- Word: select text and choose **刷新** if needed. Excel: select a cell or rectangular range; the add-in reads displayed values and the A1 address.
- Choose **发送选区到当前 Atlas 会话**. Atlas opens the paired conversation and fills a draft with the document name, selected range and text. Review and send it in Atlas.
- In Atlas, run `/office writeback <修改后的文本>`. The task pane receives the result; select the destination in Word or Excel and click **写入当前选区**.
- Use **断开此 Office 会话** to remove the pairing token from that Office profile. Generate a new code with `/office` to pair again.

The add-in server listens only on loopback and proxies only `/api/office/*` to Atlas. It uses the Microsoft Office Add-in development certificate for the HTTPS task pane origin. The pairing token is scoped to one Office add-in instance and an Atlas conversation; it does not authorize other Atlas API routes.
