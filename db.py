import datetime
from vars import MONGO_URL
from motor.motor_asyncio import AsyncIOMotorClient

class Database:
    def __init__(self, uri):
        self.client = AsyncIOMotorClient(uri)
        # Using db name 'uploader_db'
        self.db = self.client.uploader_db
        self.users = self.db.authorized_users
        self.total_users = self.db.total_users
        self.cache = self.db.file_cache

    async def is_user_authorized(self, user_id, owner_id):
        # Owner is always authorized
        if user_id == owner_id:
            return True
        user = await self.users.find_one({"user_id": user_id})
        if not user:
            return False
        expiry_date = user.get("expiry_date")
        if not expiry_date:
            return False
        if datetime.datetime.now() > expiry_date:
            return False
        return True

    async def add_user(self, user_id, name, days):
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "expiry_date": expiry_date}},
            upsert=True
        )
        return expiry_date

    async def remove_user(self, user_id):
        result = await self.users.delete_one({"user_id": user_id})
        return result.deleted_count > 0

    async def list_authorized_users(self):
        cursor = self.users.find({})
        users_list = []
        async for doc in cursor:
            users_list.append(doc)
        return users_list

    async def add_total_user(self, user_id):
        await self.total_users.update_one(
            {"user_id": user_id},
            {"$set": {"last_seen": datetime.datetime.now()}},
            upsert=True
        )

    async def list_total_users(self):
        cursor = self.total_users.find({})
        users_list = []
        async for doc in cursor:
            users_list.append(doc["user_id"])
        return users_list

    async def get_cached_file(self, url, quality, watermark):
        doc = await self.cache.find_one({
            "url": url,
            "quality": quality,
            "watermark": watermark
        })
        return doc

    async def add_cached_file(self, url, quality, watermark, file_id, file_type, caption=""):
        await self.cache.update_one(
            {
                "url": url,
                "quality": quality,
                "watermark": watermark
            },
            {
                "$set": {
                    "file_id": file_id,
                    "file_type": file_type,
                    "caption": caption,
                    "cached_at": datetime.datetime.now()
                }
            },
            upsert=True
        )

db = Database(MONGO_URL)
