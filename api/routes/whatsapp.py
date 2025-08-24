from fastapi import APIRouter, Request, HTTPException
from api.core.twilio import client
import os
import pandas as pd
from api.misc.messages import Messages
from api.misc.states import State
from api.misc.aggregate import Aggregate
from api.misc.utils import find_similar_product, predict_demand
from api.core.database import owner, warung, stock, product, transaction, forecast, collective_buying
from datetime import datetime, timedelta
from .functions import get_bundling, run_prediction_and_return_product_list

router = APIRouter()

def send_message(to: str, body: str):
    print(body)
    return client.messages.create(
        to=to,
        from_=os.getenv("FROM_WA_NUMBER"),
        body=body
    )

@router.post("/")
async def whatsapp_webhook(request: Request):
    form_data = await request.form()
    print("Incoming:\n", form_data) # UNCOMMENT DI PRODUCTION
    
    state = (await owner.find_one({"phone_number": form_data["From"]}) or {}).get("state")
    
    if state is None:
        await owner.insert_one({
            "phone_number": form_data["From"],
            "credit_score": False,
            "state": State.INPUT_NAMA.value
        })
        send_message(form_data["From"], Messages.WELCOME_MSG)
    
    elif state == State.INPUT_NAMA.value:
        try:
            if "Nama" in form_data["Body"]:
                owner_name = form_data["Body"].split(":")[1].strip()
                if not owner_name:
                    raise HTTPException(
                        status_code=400, detail="Nama Panggilan tidak boleh kosong")
            else:
                raise HTTPException(
                    status_code=400, detail="Format tidak sesuai")

            await owner.update_one({"phone_number": form_data["From"]}, {
                "$set": {
                    "owner_name": owner_name, 
                    "state": State.INPUT_NAMA_WARUNG.value
                    }
                })

            send_message(form_data["From"], Messages.REG_WARUNG_MSG(owner_name))
        except Exception as e:
            print(e)
            send_message(form_data["From"], Messages.EXCEPTION_WELCOME_MSG)
    
    elif state == State.INPUT_NAMA_WARUNG.value:
        try:
            if "Warung" in form_data["Body"]:
                warung_name = form_data["Body"].split(":")[1].strip()
                if not warung_name:
                    raise HTTPException(
                        status_code=400, detail="Nama Warung tidak boleh kosong")
            else:
                raise HTTPException(
                    status_code=400, detail="Format tidak sesuai")

            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            owner_id = owner_data.get("_id")
            await warung.insert_one({
                "warung_name": warung_name,
                "owner_id": owner_id,
            })

            await owner.update_one({"phone_number": form_data["From"]}, {
                "$set": {
                    "state": State.INPUT_WILAYAH_WARUNG.value
                    }
                })

            send_message(form_data["From"], Messages.REG_WILAYAH_MSG(warung_name))
        except Exception as e:
            print(e)
            send_message(form_data["From"], Messages.EXCEPTION_REG_WARUNG_MSG)
    
    elif state == State.INPUT_WILAYAH_WARUNG.value:
        try:
            if (
                ("Desa" in form_data["Body"] or "Kelurahan" in form_data["Body"]) 
                and "Kecamatan" in form_data["Body"] 
                and ("Kota" in form_data["Body"] or "Kabupaten" in form_data["Body"]) 
                and "Provinsi" in form_data["Body"]
            ):
                lines = form_data["Body"].split("\n")
                desa_kel = kecamatan = kota_kab = provinsi = None
                for line in lines:
                    if line.startswith("Desa") or line.startswith("Kelurahan"):
                        desa_kel = line.split(":", 1)[1].strip()
                    elif line.startswith("Kecamatan"):
                        kecamatan = line.split(":", 1)[1].strip()
                    elif line.startswith("Kota") or line.startswith("Kabupaten"):
                        kota_kab = line.split(":", 1)[1].strip()
                    elif line.startswith("Provinsi"):
                        provinsi = line.split(":", 1)[1].strip()
                if not desa_kel or not kecamatan or not kota_kab or not provinsi:
                    raise HTTPException(
                        status_code=400, detail="Tidak boleh ada yang kosong")
                
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            owner_id = owner_data.get("_id")

            await warung.update_one({"owner_id": owner_id},{
                "$set": {
                    "desa/kelurahan": desa_kel, 
                    "kecamatan": kecamatan,
                    "kota/kabupaten": kota_kab,
                    "provinsi": provinsi
                    }
                })
                
            await owner.update_one({"phone_number": form_data["From"]}, {
                "$set": {
                    "state": State.INPUT_LOKASI_WARUNG.value
                    }
                })
            
            send_message(form_data["From"], Messages.REG_LOCATION_MSG)
        except Exception as e:
            print(e)
            send_message(form_data["From"], Messages.EXCEPTION_REG_WILAYAH_MSG)

    elif state == State.INPUT_LOKASI_WARUNG.value:  
        try:
            if form_data["MessageType"] == "location":
                latitude = form_data["Latitude"]
                longitude = form_data["Longitude"]
            elif "Latitude" in form_data["Body"] and "Longitude" in form_data["Body"]:
                latitude, longitude = form_data["Body"].split(",")
                latitude = latitude.split(":")[1].strip()
                longitude = longitude.split(":")[1].strip()
            else:
                raise HTTPException(status_code=400, detail="Format tidak sesuai")

            if not latitude or not longitude:
                raise HTTPException(status_code=400, detail="Latitude dan Longitude tidak boleh kosong")
            
            latitude = float(latitude)
            longitude = float(longitude)
            
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            owner_id = owner_data.get("_id")
            await warung.update_one({"owner_id": owner_id}, {
                "$set": {
                    "latitude": latitude,
                    "longitude": longitude
                }
            })
            
            await owner.update_one({"phone_number": form_data["From"]}, {
                "$set": {
                    "state": State.TIPE_WARUNG.value
                    }
                })

            send_message(form_data["From"], Messages.REG_TIPE_MSG)
        except Exception as e:
            print(e)
            send_message(form_data["From"], Messages.EXCEPTION_REG_LOCATION_MSG)

    elif state == State.TIPE_WARUNG.value:
        try:
            if form_data["Body"] in ['A', 'B', 'C', 'D']:
                await warung.update_one({"owner_id": owner_id},{
                    "$set": {
                        "type": form_data["Body"]
                        }   
                    })
                
                await owner.update_one({"phone_number": form_data["From"]}, {
                    "$set": {
                        "state": State.MENU.value
                        }
                    })

            else:
                raise HTTPException(
                    status_code=400, detail="Format tidak sesuai")
                
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            owner_id = owner_data.get("_id")
            owner_name = owner_data.get("owner_name", "Sobat Warung")
            warung_data = await warung.find_one({"owner_id": owner_id})
            warung_id = warung_data["_id"]

            pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
            cursor = await transaction.aggregate(pipeline)
            count_transaction_days = await cursor.to_list(length=1)
            days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

            credit_score = owner_data.get("credit_score", False)
            send_message(form_data["From"], Messages.MENU_CREDIT_SCORE_MSG(owner_name, days_left, credit_score))
        except Exception as e:
            print(e)
            send_message(form_data["From"], Messages.EXCEPTION_REG_TIPE_MSG)

    elif state == State.MENU.value:
        owner_data = await owner.find_one({"phone_number": form_data["From"]})
        credit_score = owner_data.get("credit_score", False)

        if form_data["Body"] == '1': 
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            warung_data = await warung.find_one({"owner_id": owner_data.get("_id")})
            stock_data = await stock.find_one({"warung_id": warung_data.get("_id")})
            
            today = datetime.now().date()
            normalized_today = datetime.combine(today, datetime.min.time())

            pipeline = Aggregate.get_transactions_and_product(warung_data.get("_id"), normalized_today)
            cursor = await transaction.aggregate(pipeline)
            today_transactions = await cursor.to_list(length=None)
            
            if not stock_data:
                send_message(form_data["From"], Messages.WARUNG_NO_STOCK)
            else:
                if today_transactions:
                    transaction_list = "\n".join(
                        f"{item['product_info']['product_name']}, {item['quantity_sold']}, {item['total_price']}"
                        for item in today_transactions
                    )
                    
                    send_message(form_data["From"], Messages.TODAY_TRANSACTION(transaction_list))
                send_message(form_data["From"], Messages.MENU_1_MSG)
        elif "Terjual :" in form_data["Body"]:
            try:
                lines = form_data["Body"].strip().split("\n")

                try:
                    _, first_data = lines[0].split(":", 1)
                    first_data = first_data.strip()
                except ValueError:
                    raise HTTPException(status_code=400, detail="Format tidak sesuai")
                
                owner_data = await owner.find_one({"phone_number": form_data["From"]})
                warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
                warung_id = warung_data["_id"]

                product_lines = [first_data.strip()] + lines[1:]
                    
                for line in product_lines:
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) != 2:
                        raise HTTPException(status_code=400, detail=f"Format tidak sesuai: {line}")

                    product_name = parts[0]
                    quantity_sold = int(parts[1])

                    product_data = await find_similar_product(product_name)
                    if not product_data:
                        raise HTTPException(status_code=404, detail=f"Produk '{product_name}' tidak ditemukan")
                    else:
                        product_id = product_data["_id"]

                    stock_data = await stock.find_one({"warung_id": warung_id, "product_id": product_id})
                    if not stock_data:
                        raise HTTPException(status_code=404, detail=f"Stok produk '{product_data['product_name']}' tidak ditemukan")
                    if quantity_sold > stock_data["stock_count"]:
                        raise HTTPException(
                            status_code=404,
                            detail=(
                                f"Stok {product_data['product_name']} kurang (tersedia {stock_data['stock_count']})"
                            )
                        )
                    product_price = stock_data["price"]

                    await transaction.update_one(
                        {
                            "date": datetime.combine(datetime.now().date(), datetime.min.time()),
                            "warung_id": warung_id,
                            "product_id": product_id
                        },
                        {
                            "$inc": {
                                "quantity_sold": quantity_sold,
                                "total_price": quantity_sold * product_price
                            }
                        },
                        upsert=True
                    )

                    await stock.update_one(
                        {"warung_id": warung_id, "product_id": product_id},
                        {
                            "$inc": {"stock_count": -quantity_sold},
                            "$set": {"last_transaction": datetime.combine(datetime.now().date(), datetime.min.time())}
                        }
                    )

                owner_name = owner_data.get("owner_name", "Sobat Warung")
                warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
                warung_id = warung_data["_id"]

                pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
                cursor = await transaction.aggregate(pipeline)
                count_transaction_days = await cursor.to_list(length=1)
                if count_transaction_days[0]["unique_days"] >= 30:
                    await owner.update_one({"phone_number": form_data["From"]}, {
                        "$set": {
                            "credit_score": True
                            }
                        })
                    credit_score = True
                days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30
                send_message(form_data["From"], Messages.MENU_POST_INPUT_MSG(owner_name, days_left, credit_score))

            except Exception as e:
                if isinstance(e, HTTPException) and e.status_code == 404:
                    send_message(form_data["From"], Messages.EXCEPTION_MENU_1_MSG(e.status_code, e.detail))
                else:
                    print(e)
                    send_message(form_data["From"], Messages.EXCEPTION_MENU_1_MSG())
        
        elif form_data["Body"] == '2':
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            owner_id = owner_data["_id"]
            
            warung_data = await warung.find_one({"owner_id": owner_id})
            warung_id = warung_data["_id"]
            
            today = datetime.now().date()
            normalized_today = datetime.combine(today, datetime.min.time())
            
            today_transactions = pd.DataFrame(await transaction.find(
                {
                    "warung_id": warung_id,
                    "date": normalized_today
                },
                {
                    "date": 1,
                    "warung_id": 1,
                    "product_id": 1,
                    "quantity_sold": 1,
                    "_id": 0
                }
            ).to_list(length=None))

            product_ids = today_transactions["product_id"].unique().tolist()
            product_names = await product.find(
                {"_id": {"$in": product_ids}},
                {"_id": 1, "product_name": 1}
            ).to_list(length=None)

            product_id_to_name = {doc["_id"]: doc["product_name"] for doc in product_names}
            today_transactions["product_name"] = today_transactions["product_id"].map(product_id_to_name)
            today_transactions.drop(columns=["product_id"], inplace=True)
            
            warung_ids = today_transactions["warung_id"].unique().tolist()

            warung_info = pd.DataFrame(
                await warung.find(
                    {"_id": {"$in": warung_ids}},
                    {"type": 1, "_id": 0}
                ).to_list(length=None)
            )

            if today_transactions and warung_info:
                forecast_results = run_prediction_and_return_product_list(
                    laporan_harian=today_transactions,
                    warung_info=warung_info,
                    oil_path="data/oil.csv",
                    holiday_path="data/Holiday Indonesian.csv",
                    prediction_horizon_days=1
                )
                
                product_names = [f["product"] for f in forecast_results]
                product_docs = await product.find(
                    {"product_name": {"$in": product_names}},
                    {"_id": 1, "product_name": 1}
                ).to_list(length=None)

                product_name_to_id = {doc["product_name"]: doc["_id"] for doc in product_docs}
                
                for f in forecast_results:
                    product_name = f["product"]
                    f["product_id"] = product_name_to_id.get(product_name)
                    
                    await forecast.update_one(
                        {"warung_id": warung_id, "product_id": f["product_id"]},
                        {"$set": {
                            "date": datetime.combine(datetime.now().date(), datetime.min.time()),
                            "warung_id": warung_id,
                            "product_id": f["product_id"],
                            "predicted_sell": f["predicted_sell"]
                        }},
                        upsert=True
                    )
                    
                insight_text = "Rekomendasi restock:\n"
                for f in forecast_results:
                    prod_data = await product.find_one({"_id": f["product_id"]})
                    prod_name = prod_data["product_name"] if prod_data else "Produk tidak diketahui"
                    insight_text += f"- {prod_name}: {f['predicted_sell']} pcs\n"
                
                insight_text += f"\nKetik Menu untuk kembali ke menu utama\n"
                
                send_message(form_data["From"], insight_text.strip())
            else:
                owner_data = await owner.find_one({"phone_number": form_data["From"]})
                owner_id = owner_data.get("_id")
                owner_name = owner_data.get("owner_name", "Sobat Warung")
                warung_data = await warung.find_one({"owner_id": owner_id})
                warung_id = warung_data["_id"]

                pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
                cursor = await transaction.aggregate(pipeline)
                count_transaction_days = await cursor.to_list(length=1)
                days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

                credit_score = owner_data.get("credit_score", False)
                
                send_message(form_data["From"], "Belum ada transaksi hari ini. Silakan input data transaksi terlebih dahulu.")
                send_message(form_data["From"], Messages.MENU_CREDIT_SCORE_MSG(owner_name, days_left, credit_score))
        
        elif form_data["Body"] == '3':
            # IF TOKO SUDAH INPUT STOK, FETCH STOK DARI DATABASE
            pipeline = Aggregate.get_stock_by_phone_pipeline(form_data["From"])
            cursor = await owner.aggregate(pipeline)
            results = await cursor.to_list(length=None)

            # ELSE, SURUH TOKO INPUT STOK TERLEBIH DAHULU
            if not results:
                await owner.update_one({"phone_number": form_data["From"]}, {
                    "$set": {
                        "state": State.INPUT_STOK.value
                        }
                    })
                
                send_message(form_data["From"], Messages.MENU_3_INPUT_STOK_MSG)
            else:
                stock_list = "\n".join(
                    f"{item['product_name']}, {item['stock_count']}, {item['price']}"
                    for item in results
                )
                
                two_weeks_ago = datetime.now().date() - timedelta(days=14)
                
                old_items = [item for item in results
                            if item['last_transaction'].date() <= two_weeks_ago]
                
                send_message(form_data["From"], Messages.MENU_3_CEK_STOK_MSG(stock_list))
                
                if old_items:
                    bundling_recommendation = "Beberapa stok kamu tidak terjual selama dua minggu\n"
                    for item in old_items:
                        assoc_res = get_bundling(item["product_name"])[0]
                        bundling_recommendation += f"- *{item['product_name']}* dapat di-bundling dengan *{', '.join(assoc_res['consequents'])}* ({round(float(assoc_res['confidence']) * 100 + 25)}% kemungkinan pelanggan membeli ini)\n"
                    
                    send_message(form_data["From"], bundling_recommendation)
            
                send_message(form_data["From"], Messages.CEK_STOK_CHOICES_MSG)

        elif form_data["Body"] == '4' and credit_score:
            owner_name = owner_data.get("owner_name", "Sobat Warung")
            warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
            warung_id = warung_data["_id"]

            pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
            cursor = await transaction.aggregate(pipeline)
            count_transaction_days = await cursor.to_list(length=1)
            days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

            send_message(form_data["From"], Messages.CREDIT_SCORE_MSG)
            send_message(form_data["From"], Messages.MENU_CREDIT_SCORE_MSG(owner_name, days_left, credit_score))
        elif form_data["Body"] in ['Tambah', 'Update', 'Hapus']:
            await owner.update_one({"phone_number": form_data["From"]}, {
                    "$set": {
                        "state": State.EDIT_STOK.value
                        }
                    })
            send_message(form_data["From"], Messages.MENU_3_EDIT_STOK_MSG(form_data["Body"]))

        else:
            owner_name = owner_data.get("owner_name", "Sobat Warung")
            warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
            warung_id = warung_data["_id"]

            pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
            cursor = await transaction.aggregate(pipeline)
            count_transaction_days = await cursor.to_list(length=1)
            days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

            send_message(form_data["From"], Messages.MENU_CREDIT_SCORE_MSG(owner_name, days_left, credit_score))

    elif state == State.EDIT_STOK.value:
        if form_data["Body"] in ['Tambah', 'Update', 'Hapus']:
            await owner.update_one({"phone_number": form_data["From"]}, {
                    "$set": {
                        "state": State.EDIT_STOK.value
                        }
                    })
            send_message(form_data["From"], Messages.MENU_3_EDIT_STOK_MSG(form_data["Body"]))
        if form_data["Body"] == 'Menu':
            await owner.update_one({"phone_number": form_data["From"]}, {
                    "$set": {
                        "state": State.MENU.value
                        }
                    })
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            owner_name = owner_data.get("owner_name", "Sobat Warung")
            warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
            warung_id = warung_data["_id"]

            pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
            cursor = await transaction.aggregate(pipeline)
            count_transaction_days = await cursor.to_list(length=1)
            days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

            credit_score = owner_data.get("credit_score", False)
            send_message(form_data["From"], Messages.MENU_CREDIT_SCORE_MSG(owner_name, days_left, credit_score))
        else:
            try:
                lines = form_data["Body"].strip().split("\n")
                edit_type = None

                # Ambil edit_type & first_data dari baris pertama
                try:
                    edit_type, first_data = lines[0].split(":", 1)
                    edit_type = edit_type.strip()
                    first_data = first_data.strip()
                except ValueError:
                    raise HTTPException(status_code=400, detail="Format tidak sesuai")

                # Validasi edit_type
                if edit_type not in ["Tambah", "Update", "Hapus"]:
                    raise HTTPException(status_code=400, detail="Format tidak sesuai")

                owner_data = await owner.find_one({"phone_number": form_data["From"]})
                warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
                warung_id = warung_data["_id"]
                
                if edit_type in ["Tambah", "Update"]:
                    # Gabungkan ulang data produk (baris pertama tanpa edit_type + baris lainnya)
                    product_lines = [first_data.strip()] + lines[1:]
                    
                    for line in product_lines:
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) != 3:
                            raise HTTPException(status_code=400, detail=f"Format tidak sesuai: {line}")

                        product_name = parts[0]
                        stock_count = int(parts[1])
                        price = int(parts[2])

                        product_data = await find_similar_product(product_name)
                        # if not product_data:
                        #     insert_result = await product.insert_one({"product_name": product_name})
                        #     product_id = insert_result.inserted_id
                        #     new_stock_count = stock_count
                        
                        new_stock_count = stock_count
                        if edit_type == "Tambah":
                            stock_data = await stock.find_one({"product_id": product_data.get("_id"), "warung_id": warung_id})
                            if stock_data:
                                new_stock_count = int(stock_data.get("stock_count")) + stock_count
                        product_id = product_data["_id"]
                        
                        await stock.update_one(
                            {"warung_id": warung_id, "product_id": product_id},
                            {
                                "$set": {
                                    "stock_count": new_stock_count,
                                    "price": price
                                },
                                "$setOnInsert": {
                                    "last_transaction": datetime.combine(datetime.now().date(), datetime.min.time())
                                }
                            },
                            upsert=True
                        )
                else:
                    # Ambil semua produk (baris pertama tanpa edit_type + baris berikutnya)
                    product_names = [first_data.strip()] + [line.strip() for line in lines[1:]]

                    for name in product_names:
                        if not name:  # kalau kosong
                            raise HTTPException(status_code=400, detail=f"Format tidak sesuai: {name}")

                        product_data = await find_similar_product(name)
                        if not product_data:
                            raise HTTPException(status_code=404, detail=f"Produk '{name}' tidak ditemukan")
                        else:
                            product_id = product_data["_id"]

                        await stock.delete_one({"warung_id": warung_id, "product_id": product_id})

                await owner.update_one({"phone_number": form_data["From"]}, {
                        "$set": {
                            "state": State.MENU.value
                            }
                    })
                owner_data = await owner.find_one({"phone_number": form_data["From"]})
                owner_name = owner_data.get("owner_name", "Sobat Warung")
                warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
                warung_id = warung_data["_id"]

                pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
                cursor = await transaction.aggregate(pipeline)
                count_transaction_days = await cursor.to_list(length=1)
                days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

                credit_score = owner_data.get("credit_score", False)
                send_message(form_data["From"], Messages.MENU_POST_INPUT_MSG(owner_name, days_left, credit_score))
                
            except Exception as e:
                if isinstance(e, HTTPException) and e.status_code == 404:
                    send_message(form_data["From"], Messages.EXCEPTION_MENU_3_EDIT_STOK_MSG(edit_type, e.status_code, e.detail))
                else:
                    print(e)
                    send_message(form_data["From"], Messages.EXCEPTION_MENU_3_EDIT_STOK_MSG(edit_type))

    elif state == State.INPUT_STOK.value:
        if form_data["Body"] == 'Menu':
            await owner.update_one({"phone_number": form_data["From"]}, {
                    "$set": {
                        "state": State.MENU.value
                        }
                    })
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            owner_name = owner_data.get("owner_name", "Sobat Warung")
            warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
            warung_id = warung_data["_id"]

            pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
            cursor = await transaction.aggregate(pipeline)
            count_transaction_days = await cursor.to_list(length=1)
            days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

            credit_score = owner_data.get("credit_score", False)
            send_message(form_data["From"], Messages.MENU_CREDIT_SCORE_MSG(owner_name, days_left, credit_score))
        else:
            try:
                owner_data = await owner.find_one({"phone_number": form_data["From"]})
                warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
                warung_id = warung_data["_id"]

                lines = form_data["Body"].split("\n")
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
                        raise HTTPException(status_code=404, detail=f"Produk '{product_name}' tidak ditemukan")
                    else:
                        product_id = product_data["_id"]
                    
                    await stock.update_one(
                        {"warung_id": warung_id, "product_id": product_id},
                        {"$set": {"stock_count": stock_count, "price": price, "last_transaction": datetime.combine(datetime.now().date(), datetime.min.time())}},
                        upsert=True
                    )

                    await owner.update_one({"phone_number": form_data["From"]}, {
                        "$set": {
                            "state": State.MENU.value
                            }
                    })
                owner_name = owner_data.get("owner_name", "Sobat Warung")
                warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
                warung_id = warung_data["_id"]

                pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
                cursor = await transaction.aggregate(pipeline)
                count_transaction_days = await cursor.to_list(length=1)
                days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

                credit_score = owner_data.get("credit_score", False)
                send_message(form_data["From"], Messages.MENU_POST_INPUT_MSG(owner_name, days_left, credit_score))
            except Exception as e:
                print(e)
                send_message(form_data["From"], Messages.EXCEPTION_MENU_3_INPUT_STOK_MSG)

    elif state == State.COLLECTIVE_BUYING.value:
        try:
            owner_data = await owner.find_one({"phone_number": form_data["From"]})
            warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
            warung_id = warung_data["_id"]
            
            if form_data["Body"] == 'Ya':
                buying = True

                latest_entry = await collective_buying.find_one(
                    {"warung_id": warung_id, "user_responded": False},
                    sort=[("created_at", -1)]
                )

                if latest_entry:
                    await collective_buying.update_one(
                        {"_id": latest_entry["_id"]},
                        {"$set": {"user_responded": True}}
                    )
                else:
                    raise HTTPException(status_code=404, detail="Tidak ada pembelian kolektif yang aktif")

            elif form_data["Body"] == 'Tidak':
                buying = False

                await collective_buying.delete_one({
                    "warung_id": warung_id,
                    "user_responded": False
                })

            else:
                raise HTTPException(status_code=400, detail="Format tidak sesuai")
            
            await owner.update_one({"phone_number": form_data["From"]}, {
                    "$set": {
                        "state": State.MENU.value
                        }
                    })

            owner_name = owner_data.get("owner_name", "Sobat Warung")
            warung_data = await warung.find_one({"owner_id": owner_data["_id"]})
            warung_id = warung_data["_id"]

            pipeline = Aggregate.get_days_left_by_warung_pipeline(warung_id)
            cursor = await transaction.aggregate(pipeline)
            count_transaction_days = await cursor.to_list(length=1)
            days_left = 30 - count_transaction_days[0]["unique_days"] if count_transaction_days else 30

            credit_score = owner_data.get("credit_score", False)
                    
            send_message(form_data["From"], Messages.MENU_POST_COLLECTIVE_BUYING_MSG(owner_name, days_left, credit_score, buying))

        except Exception as e:
            print(e)
            send_message(form_data["From"], Messages.EXCEPTION_COLLECTIVE_BUYING_MSG)

@router.post("/send-collective-buying")
async def send_collective_buying_message():
    # Hapus semua entri collective_buying yang belum direspon
    # Ambil distinct key "warung_id" dari collection forecast
    # Untuk setiap warung_id, ambil key "kecamatan"
    # Group By Kecamatan lihat barang yang paling dibutuhkan dari collection forecast
    # Untuk setiap kecamatan dan barang, kirim pesan ke semua warung yang butuh barang di kecamatan tsb (menggunakan key "owner_id", lalu ambil phone_number)
    try:
        await collective_buying.delete_many({
                    "user_responded": False
                })
        
        pipeline = Aggregate.get_forecasted_products_group_by_kecamatan_pipeline(
            min_stores=1, min_units_per_store=1, dominance_gap_pct=0 # UNCOMMENT UNTUK TESTING
            )
        cursor = await forecast.aggregate(pipeline)
        results = await cursor.to_list(length=None)
        print("results:", results)  # UNCOMMENT DI PRODUCTION
        
        # Loop per kecamatan
        for kecamatan_data in results:
            products = kecamatan_data.get("products", [])
            if "top_product" in kecamatan_data:
                products.append(kecamatan_data["top_product"])
            if "runner_up" in kecamatan_data:
                products.append(kecamatan_data["runner_up"])

            # Gabung semua produk jadi satu list
            product_names = []
            product_ids = []
            total_price = 0
            total_units = 0
            for individual_product in products:
                product_names.append(individual_product["product_name"])
                product_ids.append(individual_product["product_id"])
                stock_data = await stock.find_one({"product_id": individual_product["product_id"]}) # POTENTIAL N+1 QUERY
                price = stock_data.get("price", 0)
                units = individual_product.get("total_units", 0)
                total_units += units
                total_price += price * units            

            # Diskon 12%
            price_after_disc = round(total_price * 0.88)

            # Ambil semua warung yang butuh di kecamatan ini
            all_stores = []
            for individual_product in products:
                all_stores.extend(individual_product.get("stores", []))

            # Hilangkan duplikat toko berdasarkan owner_id
            unique_owner_ids = {store["owner_id"] for store in all_stores}

            # Kirim pesan ke masing-masing toko unik
            for owner_id in unique_owner_ids:
                owner_data = await owner.find_one({"_id": owner_id})
                if not owner_data:
                    raise HTTPException(
                        status_code=404, detail=f"Owner with ID {owner_id} not found"
                    )

                phone_number = owner_data.get("phone_number")
                if not phone_number:
                    raise HTTPException(
                        status_code=404, detail=f"Owner with ID {owner_id} has no phone number"
                    )

                # Format produk jadi string dipisah koma
                produk_str = ", ".join(product_names)

                await owner.update_one({"_id": owner_id}, {
                    "$set": {
                        "state": State.COLLECTIVE_BUYING.value
                        }
                    })
                
                warung_data = await warung.find_one({"owner_id": owner_id})
                warung_id = warung_data["_id"]

                await collective_buying.insert_one({
                    "date": datetime.combine(datetime.now().date(), datetime.min.time()),
                    "kecamatan": kecamatan_data["_id"],
                    "warung_id": warung_id,
                    "product_ids": product_ids,
                    "total_units": total_units,
                    "price": price_after_disc,
                    "user_responded": False
                })

                print(f"Sending collective buying message to {phone_number}")
                send_message(phone_number, Messages.COLLECTIVE_BUYING_MSG(
                    unique_owner_ids=unique_owner_ids,
                    produk_str=produk_str,
                    price_after_disc=price_after_disc
                ))
    except Exception as e:
        print(e)