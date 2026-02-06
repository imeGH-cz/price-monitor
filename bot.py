import os
import json
import re
import time
import threading
import requests
from bs4 import BeautifulSoup
import telebot

# === CONFIG ===
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8231803470:AAEVTDZqlZavh22ekIV5i0W5lzQ7bOYgHeI")
OWNER_ID = int(os.environ.get("OWNER_ID", "498318140"))

bot = telebot.TeleBot(BOT_TOKEN)

# === DATA STORAGE (in-memory + file) ===
DATA_FILE = "prices_data.json"

COMPETITORS = {
    "MorySkin": "https://moryskin.com",
    "Hyaloo": "https://hyaloo.de",
    "AUDERMAESTHETIC": "https://www.auderm.de",
    "Jollifill": "https://jolifill.de",
    "hyamarkt": "https://www.hyamarkt.de",
    "FARMA MEDICAL": "https://farma-medical.de"
}

BRANDS = ["Jalupro", "DSD", "Hydropeptide", "MD:ceuticals"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
}


def load_data():
    """Load prices from file"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_updated": None, "prices": {}}


def save_data(data):
    """Save prices to file"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# === SCRAPERS ===

def scrape_moryskin_jalupro():
    """Scrape Jalupro products from MorySkin"""
    results = []
    urls_to_check = [
        "https://moryskin.com/produkt-kategorie/dermal-filler/jalupro/",
        "https://moryskin.com/produkt-kategorie/mesotherapie/"
    ]
    
    try:
        for cat_url in urls_to_check:
            resp = requests.get(cat_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.content, "lxml")
            
            # Find product links
            for link in soup.select("a.product--image, a.product--title"):
                href = link.get("href", "")
                if "jalupro" in href.lower() and href not in [r["url"] for r in results]:
                    # Visit product page for accurate price
                    try:
                        prod_resp = requests.get(href, headers=HEADERS, timeout=15)
                        prod_soup = BeautifulSoup(prod_resp.content, "lxml")
                        
                        # Get product name
                        name_tag = prod_soup.select_one("h1.product--title, h1")
                        name = name_tag.text.strip() if name_tag else ""
                        if not name or "jalupro" not in name.lower():
                            continue
                        
                        # Get price from product page
                        price_tag = prod_soup.select_one("meta[itemprop='price']")
                        if price_tag:
                            price = float(price_tag.get("content", "0"))
                        else:
                            price_span = prod_soup.select_one("span.product--price")
                            if price_span:
                                m = re.search(r"(\d+[.,]\d+)", price_span.text.replace(".", "").replace(",", "."))
                                price = float(m.group(1)) if m else 0
                            else:
                                continue
                        
                        # Check availability
                        avail = True
                        not_avail = prod_soup.select_one(".product--buybox .is--hidden, .product--not-available")
                        if not_avail or "nicht zur Verfügung" in prod_resp.text or "Ausverkauft" in prod_resp.text:
                            avail = False
                        
                        if price > 0:
                            results.append({
                                "name": name,
                                "price": price,
                                "url": href,
                                "available": avail,
                                "brand": "Jalupro"
                            })
                    except Exception as e:
                        print(f"  Error on {href}: {e}")
                        
    except Exception as e:
        print(f"Error scraping MorySkin: {e}")
    
    return results


def scrape_hyaloo_brand(brand):
    """Scrape products from Hyaloo by brand"""
    results = []
    search_url = f"https://hyaloo.de/de_DE/searchquery/{brand}/1/phot/5?url={brand}"
    
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return results
        soup = BeautifulSoup(resp.content, "lxml")
        
        # Find product cards
        products = soup.select(".product--box, .product-card, .product--info")
        for prod in products:
            name_tag = prod.select_one(".product--title a, .product--title, a.product--title")
            price_tag = prod.select_one(".product--price, .price--default")
            
            if not name_tag or not price_tag:
                continue
            
            name = name_tag.text.strip()
            if brand.lower() not in name.lower():
                continue
            
            # Parse price
            price_text = price_tag.text.strip()
            m = re.search(r"(\d+[.,]\d+)", price_text.replace(".", "").replace(",", "."))
            if not m:
                continue
            price = float(m.group(1))
            
            # Get URL
            href = name_tag.get("href", "")
            if not href.startswith("http"):
                href = "https://hyaloo.de" + href if href.startswith("/") else search_url
            
            # Check availability
            avail = True
            if "nicht auf Lager" in prod.text or "ausverkauft" in prod.text.lower():
                avail = False
            
            results.append({
                "name": name,
                "price": price,
                "url": href,
                "available": avail,
                "brand": brand
            })
    except Exception as e:
        print(f"Error scraping Hyaloo for {brand}: {e}")
    
    return results


def scrape_auderm_brand(brand):
    """Scrape products from AUDERMAESTHETIC (auderm.de) by brand"""
    results = []
    search_terms = {
        "Jalupro": "jalupro",
        "DSD": "dsd",
        "Hydropeptide": "hydropeptide",
        "MD:ceuticals": "md+ceuticals"
    }
    
    try:
        # Try collections page
        collections_url = "https://www.auderm.de/collections/bio-revitalisierung"
        resp = requests.get(collections_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return results
        soup = BeautifulSoup(resp.content, "lxml")
        
        # Find products matching brand
        for prod in soup.select(".product-card, .grid-product, [class*='product']"):
            name_tag = prod.select_one("a[href*='products'], .product-title, h3 a, h2 a")
            price_tag = prod.select_one("[class*='price'], .money")
            
            if not name_tag:
                continue
            
            name = name_tag.text.strip()
            if brand.lower() not in name.lower():
                continue
            
            href = name_tag.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.auderm.de" + href
            
            price = 0
            if price_tag:
                m = re.search(r"(\d+[.,]\d+)", price_tag.text.replace(".", "").replace(",", "."))
                if m:
                    price = float(m.group(1))
            
            avail = True
            if "ausverkauft" in prod.text.lower() or "sold out" in prod.text.lower():
                avail = False
            
            if price > 0:
                results.append({
                    "name": name,
                    "price": price,
                    "url": href,
                    "available": avail,
                    "brand": brand,
                    "note": "exkl. MwSt."
                })
    except Exception as e:
        print(f"Error scraping AUDERMAESTHETIC for {brand}: {e}")
    
    return results


def scrape_hyamarkt_brand(brand):
    """Scrape products from hyamarkt.de by brand"""
    results = []
    search_url = f"https://www.hyamarkt.de/?s={brand}"
    
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return results
        soup = BeautifulSoup(resp.content, "lxml")
        
        for prod in soup.select(".product, .wc-block-grid__product, li.product"):
            name_tag = prod.select_one("h2 a, .woocommerce-loop-product__title a, a.woocommerce-LoopProduct-link")
            price_tag = prod.select_one(".price .amount, .woocommerce-Price-amount")
            
            if not name_tag:
                continue
            
            name = name_tag.text.strip()
            if brand.lower() not in name.lower():
                continue
            
            href = name_tag.get("href", search_url)
            
            price = 0
            if price_tag:
                m = re.search(r"(\d+[.,]\d+)", price_tag.text.replace(".", "").replace(",", "."))
                if m:
                    price = float(m.group(1))
            
            if price > 0:
                results.append({
                    "name": name,
                    "price": price,
                    "url": href,
                    "available": True,
                    "brand": brand
                })
    except Exception as e:
        print(f"Error scraping hyamarkt for {brand}: {e}")
    
    return results


def run_full_scrape():
    """Run all scrapers and return structured data"""
    print("=== Starting full scrape ===")
    all_data = {
        "last_updated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "prices": {}
    }
    
    # MorySkin
    print("Scraping MorySkin...")
    moryskin_data = scrape_moryskin_jalupro()
    if moryskin_data:
        all_data["prices"]["MorySkin"] = {"Jalupro": moryskin_data}
    
    # Hyaloo
    print("Scraping Hyaloo...")
    for brand in BRANDS:
        hyaloo_data = scrape_hyaloo_brand(brand)
        if hyaloo_data:
            if "Hyaloo" not in all_data["prices"]:
                all_data["prices"]["Hyaloo"] = {}
            all_data["prices"]["Hyaloo"][brand] = hyaloo_data
    
    # AUDERMAESTHETIC
    print("Scraping AUDERMAESTHETIC...")
    for brand in BRANDS:
        auderm_data = scrape_auderm_brand(brand)
        if auderm_data:
            if "AUDERMAESTHETIC" not in all_data["prices"]:
                all_data["prices"]["AUDERMAESTHETIC"] = {}
            all_data["prices"]["AUDERMAESTHETIC"][brand] = auderm_data
    
    # hyamarkt
    print("Scraping hyamarkt...")
    for brand in BRANDS:
        hyamarkt_data = scrape_hyamarkt_brand(brand)
        if hyamarkt_data:
            if "hyamarkt" not in all_data["prices"]:
                all_data["prices"]["hyamarkt"] = {}
            all_data["prices"]["hyamarkt"][brand] = hyamarkt_data
    
    # Jollifill & FARMA MEDICAL - note as checked
    all_data["prices"]["Jollifill"] = {"_note": "Требует подтверждения статуса клиента. Товары не доступны в открытом доступе."}
    all_data["prices"]["FARMA MEDICAL"] = {"_note": "Сайт недоступен или не содержит отслеживаемых брендов."}
    
    print(f"=== Scrape complete: {time.strftime('%H:%M:%S')} ===")
    save_data(all_data)
    return all_data


# === BOT HANDLERS ===

@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "📊 <b>Price Monitor Bot</b>\n\n"
        "Мониторинг цен конкурентов по брендам:\n"
        "Jalupro, DSD, Hydropeptide, MD:ceuticals\n\n"
        "📋 <b>Команды:</b>\n"
        "/prices — актуальные цены\n"
        "/jalupro — цены Jalupro\n"
        "/dsd — цены DSD\n"
        "/hydropeptide — цены Hydropeptide\n"
        "/mdceuticals — цены MD:ceuticals\n"
        "/scrape — обновить данные\n"
        "/status — статус системы\n"
        "/help — помощь",
        parse_mode="HTML"
    )


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.send_message(
        message.chat.id,
        "🔍 <b>Мониторинг цен конкурентов</b>\n\n"
        "Отслеживаемые сайты:\n"
        "• MorySkin\n• Hyaloo\n• AUDERMAESTHETIC\n"
        "• Jollifill\n• hyamarkt\n• FARMA MEDICAL\n\n"
        "Отслеживаемые бренды:\n"
        "• Jalupro\n• DSD\n• Hydropeptide\n• MD:ceuticals\n\n"
        "💡 Цены со ссылками ведут на первоисточник.\n"
        "❌ Зачеркнутые цены = нет в наличии.",
        parse_mode="HTML"
    )


def format_brand_prices(data, brand):
    """Format prices for a specific brand across all competitors"""
    msg = f"📊 <b>{brand}</b>\n"
    msg += f"<i>Обновлено: {data.get('last_updated', 'N/A')}</i>\n\n"
    
    found_any = False
    
    for competitor in ["MorySkin", "Hyaloo", "AUDERMAESTHETIC", "Jollifill", "hyamarkt", "FARMA MEDICAL"]:
        comp_data = data.get("prices", {}).get(competitor, {})
        
        # Check for notes
        note = comp_data.get("_note", "")
        if note:
            msg += f"🏪 <b>{competitor}</b>\n"
            msg += f"  ⚠️ <i>{note}</i>\n\n"
            continue
        
        brand_products = comp_data.get(brand, [])
        if not brand_products:
            msg += f"🏪 <b>{competitor}</b>\n"
            msg += f"  ❌ Товары {brand} не найдены\n\n"
            continue
        
        found_any = True
        msg += f"🏪 <b>{competitor}</b>\n"
        for p in brand_products:
            name = p["name"]
            price = p["price"]
            url = p["url"]
            avail = p.get("available", True)
            note_p = p.get("note", "")
            
            if avail:
                msg += f'  ✅ {name}: <a href="{url}">€{price:.2f}</a>'
            else:
                msg += f"  ❌ {name}: <s>€{price:.2f}</s> (нет в наличии)"
            
            if note_p:
                msg += f" <i>({note_p})</i>"
            msg += "\n"
        msg += "\n"
    
    if not found_any:
        msg += "\n⚠️ <b>Бренд не найден ни у одного конкурента.</b>\n"
        msg += "Рекомендуется проверить специализированные магазины.\n"
    
    return msg


@bot.message_handler(commands=["prices"])
def cmd_prices(message):
    data = load_data()
    if not data.get("last_updated"):
        bot.send_message(message.chat.id, "❌ Данные еще не собраны. Используйте /scrape")
        return
    
    for brand in BRANDS:
        msg = format_brand_prices(data, brand)
        try:
            bot.send_message(message.chat.id, msg, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            bot.send_message(message.chat.id, f"Ошибка отправки {brand}: {e}")


@bot.message_handler(commands=["jalupro"])
def cmd_jalupro(message):
    data = load_data()
    if not data.get("last_updated"):
        bot.send_message(message.chat.id, "❌ Данные еще не собраны. Используйте /scrape")
        return
    msg = format_brand_prices(data, "Jalupro")
    bot.send_message(message.chat.id, msg, parse_mode="HTML", disable_web_page_preview=True)


@bot.message_handler(commands=["dsd"])
def cmd_dsd(message):
    data = load_data()
    if not data.get("last_updated"):
        bot.send_message(message.chat.id, "❌ Данные еще не собраны. Используйте /scrape")
        return
    msg = format_brand_prices(data, "DSD")
    bot.send_message(message.chat.id, msg, parse_mode="HTML", disable_web_page_preview=True)


@bot.message_handler(commands=["hydropeptide"])
def cmd_hydropeptide(message):
    data = load_data()
    if not data.get("last_updated"):
        bot.send_message(message.chat.id, "❌ Данные еще не собраны. Используйте /scrape")
        return
    msg = format_brand_prices(data, "Hydropeptide")
    bot.send_message(message.chat.id, msg, parse_mode="HTML", disable_web_page_preview=True)


@bot.message_handler(commands=["mdceuticals"])
def cmd_mdceuticals(message):
    data = load_data()
    if not data.get("last_updated"):
        bot.send_message(message.chat.id, "❌ Данные еще не собраны. Используйте /scrape")
        return
    msg = format_brand_prices(data, "MD:ceuticals")
    bot.send_message(message.chat.id, msg, parse_mode="HTML", disable_web_page_preview=True)


@bot.message_handler(commands=["scrape"])
def cmd_scrape(message):
    bot.send_message(message.chat.id, "⏳ Собираю данные со всех сайтов... Это займет 1-2 минуты.")
    try:
        data = run_full_scrape()
        
        # Count results
        total = 0
        for comp in data.get("prices", {}).values():
            for brand_data in comp.values():
                if isinstance(brand_data, list):
                    total += len(brand_data)
        
        bot.send_message(
            message.chat.id,
            f"✅ <b>Сбор данных завершен!</b>\n\n"
            f"📊 Найдено товаров: {total}\n"
            f"🕐 Обновлено: {data['last_updated']}\n\n"
            f"Используйте /prices для просмотра всех цен\n"
            f"или /jalupro /dsd /hydropeptide /mdceuticals для конкретного бренда",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при сборе данных: {e}")


@bot.message_handler(commands=["status"])
def cmd_status(message):
    data = load_data()
    
    total = 0
    comp_stats = []
    for comp_name in ["MorySkin", "Hyaloo", "AUDERMAESTHETIC", "Jollifill", "hyamarkt", "FARMA MEDICAL"]:
        comp = data.get("prices", {}).get(comp_name, {})
        count = 0
        for brand_data in comp.values():
            if isinstance(brand_data, list):
                count += len(brand_data)
        total += count
        note = comp.get("_note", "")
        if note:
            comp_stats.append(f"  ⚠️ {comp_name}: {note[:50]}")
        elif count > 0:
            comp_stats.append(f"  ✅ {comp_name}: {count} товаров")
        else:
            comp_stats.append(f"  ❌ {comp_name}: нет данных")
    
    msg = (
        f"📊 <b>Статус системы</b>\n\n"
        f"🕐 Последнее обновление: {data.get('last_updated', 'Нет данных')}\n"
        f"📦 Всего товаров: {total}\n\n"
        f"<b>Конкуренты:</b>\n" + "\n".join(comp_stats) + "\n\n"
        f"💡 Используйте /scrape для обновления данных"
    )
    bot.send_message(message.chat.id, msg, parse_mode="HTML")


# === MAIN ===
if __name__ == "__main__":
    print(f"Bot starting... Token: {BOT_TOKEN[:10]}...")
    print(f"Owner ID: {OWNER_ID}")
    
    # Run initial scrape in background
    def initial_scrape():
        time.sleep(3)
        print("Running initial scrape...")
        run_full_scrape()
        print("Initial scrape complete!")
    
    threading.Thread(target=initial_scrape, daemon=True).start()
    
    # Start bot
    print("Bot is running 24/7!")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
