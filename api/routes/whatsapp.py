from fastapi import APIRouter, Request, HTTPException, Query
from api.core.twilio import client
import os
from api.core.config import Settings
from api.misc.messages import Messages
from api.misc.states import State
from api.misc.aggregate import Aggregate
from api.misc.utils import find_similar_product
from api.core.database import owner, warung, stock, product
from datetime import datetime

router = APIRouter()

# def await Messages.send_base_message(to: str, body: str):
#     return client.messages.create(
#         to=to,
#         from_=os.getenv("FROM_WA_NUMBER"),
#         body=body
#     )

@router.get("/")
def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    if mode == "subscribe" and token == Settings.META_VERIFY_TOKEN:
        return int(challenge)
    return {"error": "Verification failed"}

@router.post("/")
async def whatsapp_webhook(request: Request):
    form_data = await request.json()
    print("Incoming:\n", form_data) # HAPUS DI PRODUCTION
    
    state = (await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}) or {}).get("state")
    
    if state is None:
        await owner.insert_one({
            "phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"],
            "state": State.INPUT_NAMA.value
        })
        await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.WELCOME_MSG)
    
    elif state == State.INPUT_NAMA.value:
        try:
            if "Nama :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]:
                owner_name = form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"].split("Nama :")[1].strip()
                if not owner_name:
                    raise HTTPException(
                        status_code=400, detail="Nama Panggilan tidak boleh kosong")
            else:
                raise HTTPException(
                    status_code=400, detail="Format tidak sesuai")

            await owner.update_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}, {
                "$set": {
                    "owner_name": owner_name, 
                    "state": State.INPUT_NAMA_WARUNG.value
                    }
                })

            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.REG_WARUNG_MSG(owner_name))
        except Exception:
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.EXCEPTION_WELCOME_MSG)
    
    elif state == State.INPUT_NAMA_WARUNG.value:
        try:
            if "Warung :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]:
                warung_name = form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"].split("Warung :")[1].strip()
                if not warung_name:
                    raise HTTPException(
                        status_code=400, detail="Nama Warung tidak boleh kosong")
            else:
                raise HTTPException(
                    status_code=400, detail="Format tidak sesuai")

            owner_data = await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]})
            owner_id = owner_data.get("_id")
            await warung.insert_one({
                "warung_name": warung_name,
                "owner_id": owner_id,
            })

            await owner.update_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}, {
                "$set": {
                    "state": State.INPUT_WILAYAH_WARUNG.value
                    }
                })

            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.REG_WILAYAH_MSG(warung_name))
        except Exception:
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.EXCEPTION_REG_WARUNG_MSG)
    
    elif state == State.INPUT_WILAYAH_WARUNG.value:
        try:
            if (
                ("Desa :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] or "Kelurahan :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]) 
                and "Kecamatan :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] 
                and ("Kota :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] or "Kabupaten :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]) 
                and "Provinsi :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]
            ):
                lines = form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"].split("\n")
                desa_kel = kecamatan = kota_kab = provinsi = None
                for line in lines:
                    if line.startswith("Desa :") or line.startswith("Kelurahan :"):
                        desa_kel = line.split(":", 1)[1].strip()
                    elif line.startswith("Kecamatan :"):
                        kecamatan = line.split(":", 1)[1].strip()
                    elif line.startswith("Kota :") or line.startswith("Kabupaten :"):
                        kota_kab = line.split(":", 1)[1].strip()
                    elif line.startswith("Provinsi :"):
                        provinsi = line.split(":", 1)[1].strip()
                if not desa_kel or not kecamatan or not kota_kab or not provinsi:
                    raise HTTPException(
                        status_code=400, detail="Tidak boleh ada yang kosong")
                
            owner_data = await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]})
            owner_id = owner_data.get("_id")

            await warung.update_one({"owner_id": owner_id},{
                "$set": {
                    "desa/kelurahan": desa_kel, 
                    "kecamatan": kecamatan,
                    "kota/kabupaten": kota_kab,
                    "provinsi": provinsi
                    }
                })
                
            await owner.update_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}, {
                "$set": {
                    "state": State.INPUT_LOKASI_WARUNG.value
                    }
                })
            
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.REG_LOCATION_MSG())
        except Exception:
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.EXCEPTION_REG_WILAYAH_MSG)

    elif state == State.INPUT_LOKASI_WARUNG.value:  
        try:
            if form_data["MessageType"] == "location":
                latitude = form_data["Latitude"]
                longitude = form_data["Longitude"]
            elif "Latitude :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]:
                latitude = form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"].split("Latitude :")[1].split(",")[0].strip()
                longitude = form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"].split("Longitude :")[1].strip()
            else:
                raise HTTPException(status_code=400, detail="Format tidak sesuai")

            if not latitude or not longitude:
                raise HTTPException(status_code=400, detail="Latitude dan Longitude tidak boleh kosong")
            
            latitude = float(latitude)
            longitude = float(longitude)
            
            owner_data = await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]})
            owner_id = owner_data.get("_id")
            await warung.update_one({"owner_id": owner_id}, {
                "$set": {
                    "latitude": latitude,
                    "longitude": longitude
                }
            })
            
            await owner.update_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}, {
                "$set": {
                    "state": State.TIPE_WARUNG.value
                    }
                })

            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.REG_TIPE_MSG())
        except Exception as e:
            print("Error :", e)
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.EXCEPTION_REG_LOCATION_MSG)

    elif state == State.TIPE_WARUNG.value:
        try:
            if form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] in ['A', 'B', 'C', 'D']:
                owner_data = await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]})
                owner_id = owner_data.get("_id")
                owner_name = owner_data.get("owner_name", "Sobat Warung")
                await warung.update_one({"owner_id": owner_id},{
                    "$set": {
                        "type": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]
                        }
                    })
                
                await owner.update_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}, {
                    "$set": {
                        "state": State.MENU.value
                        }
                    })

            else:
                raise HTTPException(
                    status_code=400, detail="Format tidak sesuai")
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.MENU_MSG(owner_name))
        except Exception:
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.EXCEPTION_REG_TIPE_MSG)

    elif state == State.MENU.value:
        if form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] == '1': 
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.MENU_1_MSG())
        elif "Terjual :" in form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]:
            try:
                pass
            except Exception:
                await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.EXCEPTION_MENU_1_MSG)
        
        elif form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] == '2':
            # Panggil Function Predict Model Forecast
            pass 
        
        elif form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] == '3':
            # IF TOKO SUDAH INPUT STOK, FETCH STOK DARI DATABASE
            pipeline = Aggregate.get_stock_by_phone_pipeline(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"])
            cursor = await owner.aggregate(pipeline)
            results = await cursor.to_list(length=None)

            # ELSE, SURUH TOKO INPUT STOK TERLEBIH DAHULU
            if not results:
                await owner.update_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}, {
                    "$set": {
                        "state": State.INPUT_STOK.value
                        }
                    })
                
                await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.MENU_3_INPUT_STOK_MSG)
            else:
                stock_list = "\n".join(
                    f"{item['product_name']}, {item['stock_count']}, {item['price']}"
                    for item in results
                )

                await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.MENU_3_CEK_STOK_MSG(stock_list))
        else:
            owner_name = (await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}) or {}).get("owner_name", "Sobat Warung")
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.MENU_MSG(owner_name))

    elif state == State.INPUT_STOK.value:
        try:
            owner_data = await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]})
            warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
            warung_id = warung_data["_id"]

            lines = form_data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"].split("\n")
            for line in lines:
                parts = line.split(",")
                if len(parts) != 3:
                    raise HTTPException(
                        status_code=400, detail="Format tidak sesuai")
                
                product_name = parts[0].strip()
                stock_count = int(parts[1].strip())
                price = int(parts[2].strip())

                product_data = await find_similar_product(product_name)
                if not product_data:
                    insert_result = await product.insert_one({"product_name": product_name})
                    product_id = insert_result.inserted_id
                else:
                    product_id = product_data["_id"]
                
                await stock.update_one(
                    {"warung_id": warung_id, "product_id": product_id},
                    {"$set": {"stock_count": stock_count, "price": price, "last_transaction": datetime.now()}},
                    upsert=True
                )

                await owner.update_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]}, {
                    "$set": {
                        "state": State.MENU.value
                        }
                })
                owner_data = await owner.find_one({"phone_number": form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]})
                owner_name = owner_data.get("owner_name", "Sobat Warung")
                await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.MENU_POST_INPUT_MSG(owner_data["owner_name"]))
        except Exception:
            await Messages.send_base_message(form_data["entry"][0]["changes"][0]["value"]["messages"][0]["from"], Messages.EXCEPTION_MENU_3_INPUT_STOK_MSG)