## commands
Telegram -> wmstudio_director_bot -> start -> ui in wmstudio director page call those to confirm info
Call telegram_get_me (return data with name, username, id, type)
Call telegram_get_updates (return data with updates)

## to get chat id
first you need to find wmstudio_director_bot in telegram and send it a message
then `call telegram_get_updates` to get the chat id