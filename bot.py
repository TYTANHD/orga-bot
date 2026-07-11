import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import pytz
import json
import os

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")

CHANNEL_AUFSTELLUNG    = 1525504701582540954
CHANNEL_ARCHIV         = 1525504784872771614
CHANNEL_ABMELDUNG      = 1525504732137783306

TIMEZONE = pytz.timezone("Europe/Berlin")

EMBED_COLOR = 0x8b0000  # Dunkelrot

# Wird per /setrolle Command gesetzt und gespeichert
DATA_FILE = "data.json"

# ─── DATA HANDLER ─────────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "rolle_id": None,
        "aktuelle_nachricht_id": None,
        "abstimmung": {},       # { user_id: "ja" | "nein" | "vielleicht" }
        "abmeldungen": {},      # { user_id: { "von": str, "bis": str, "grund": str } }
        "eingefroren": False
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

# ─── BOT SETUP ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── HILFSFUNKTIONEN ──────────────────────────────────────────────────────────
def get_morgen_datum():
    now = datetime.now(TIMEZONE)
    morgen = now + timedelta(days=1)
    wochentage = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
    return f"{wochentage[morgen.weekday()]}, {morgen.strftime('%d.%m.%Y')}"

def get_heute_datum():
    now = datetime.now(TIMEZONE)
    wochentage = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
    return f"{wochentage[now.weekday()]}, {now.strftime('%d.%m.%Y')}"

async def get_rolle_mitglieder(guild):
    rolle_id = data.get("rolle_id")
    if not rolle_id:
        return []
    rolle = guild.get_role(int(rolle_id))
    if not rolle:
        return []
    return [m for m in rolle.members if not m.bot]

def build_embed(datum, mitglieder, eingefroren=False):
    abstimmung = data.get("abstimmung", {})
    abmeldungen = data.get("abmeldungen", {})

    ja_liste        = []
    nein_liste      = []
    vielleicht_liste= []
    abgemeldet_liste= []
    offen_liste     = []

    for m in mitglieder:
        uid = str(m.id)
        if uid in abmeldungen:
            abgemeldet_liste.append(m.display_name)
        elif uid in abstimmung:
            status = abstimmung[uid]
            if status == "ja":
                ja_liste.append(m.display_name)
            elif status == "nein":
                nein_liste.append(m.display_name)
            elif status == "vielleicht":
                vielleicht_liste.append(m.display_name)
        else:
            offen_liste.append(m.display_name)

    titel = f"🔰 Tägliche Aufstellung ! 🔰"
    if eingefroren:
        titel += " *(Eingefroren)*"

    embed = discord.Embed(
        title=titel,
        description=f"📅 **{datum}**\n🕐 Aufstellung: **20:30 Uhr**\n{'🔒 Abstimmung geschlossen!' if eingefroren else '✅ Jetzt abstimmen!'}",
        color=EMBED_COLOR
    )

    embed.add_field(
        name=f"✅ Dabei ({len(ja_liste)})",
        value="\n".join(ja_liste) if ja_liste else "*Niemand*",
        inline=True
    )
    embed.add_field(
        name=f"❌ Nicht dabei ({len(nein_liste)})",
        value="\n".join(nein_liste) if nein_liste else "*Niemand*",
        inline=True
    )
    embed.add_field(
        name=f"❓ Vielleicht ({len(vielleicht_liste)})",
        value="\n".join(vielleicht_liste) if vielleicht_liste else "*Niemand*",
        inline=True
    )
    embed.add_field(
        name=f"🏖️ Abgemeldet ({len(abgemeldet_liste)})",
        value="\n".join(abgemeldet_liste) if abgemeldet_liste else "*Niemand*",
        inline=True
    )
    if offen_liste and not eingefroren:
        embed.add_field(
            name=f"⏳ Noch nicht abgestimmt ({len(offen_liste)})",
            value="\n".join(offen_liste),
            inline=False
        )
    elif offen_liste and eingefroren:
        embed.add_field(
            name=f"🚨 Nicht abgestimmt ({len(offen_liste)})",
            value="\n".join(offen_liste) + "\n*(Keine Abstimmung bis 20:25 Uhr)*",
            inline=False
        )

    embed.set_footer(text="Narco City RP · Orga Management")
    embed.timestamp = datetime.now(TIMEZONE)
    return embed

# ─── VIEWS (BUTTONS) ──────────────────────────────────────────────────────────
class AufstellungView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_berechtigung(self, interaction: discord.Interaction):
        if data.get("eingefroren"):
            await interaction.response.send_message(
                "🔒 Die Abstimmung ist bereits geschlossen!", ephemeral=True
            )
            return False
        rolle_id = data.get("rolle_id")
        if not rolle_id:
            await interaction.response.send_message(
                "❌ Keine Rolle gesetzt. Admin: /setrolle benutzen.", ephemeral=True
            )
            return False
        rolle = interaction.guild.get_role(int(rolle_id))
        if rolle not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ Du hast keine Berechtigung für diese Abstimmung.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ Ich komme", style=discord.ButtonStyle.success, custom_id="btn_ja")
    async def btn_ja(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_berechtigung(interaction):
            return
        data["abstimmung"][str(interaction.user.id)] = "ja"
        # Abmeldung entfernen wenn jemand doch kommt
        data["abmeldungen"].pop(str(interaction.user.id), None)
        save_data(data)
        await update_nachricht(interaction)
        await interaction.response.send_message("✅ Du hast mit **Ich komme** abgestimmt!", ephemeral=True)

    @discord.ui.button(label="❌ Ich komme nicht", style=discord.ButtonStyle.danger, custom_id="btn_nein")
    async def btn_nein(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_berechtigung(interaction):
            return
        data["abstimmung"][str(interaction.user.id)] = "nein"
        data["abmeldungen"].pop(str(interaction.user.id), None)
        save_data(data)
        await update_nachricht(interaction)
        await interaction.response.send_message("❌ Du hast mit **Ich komme nicht** abgestimmt!", ephemeral=True)

    @discord.ui.button(label="❓ Vielleicht", style=discord.ButtonStyle.secondary, custom_id="btn_vielleicht")
    async def btn_vielleicht(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_berechtigung(interaction):
            return
        data["abstimmung"][str(interaction.user.id)] = "vielleicht"
        data["abmeldungen"].pop(str(interaction.user.id), None)
        save_data(data)
        await update_nachricht(interaction)
        await interaction.response.send_message("❓ Du hast mit **Vielleicht** abgestimmt!", ephemeral=True)

async def update_nachricht(interaction: discord.Interaction):
    msg_id = data.get("aktuelle_nachricht_id")
    if not msg_id:
        return
    kanal = interaction.guild.get_channel(CHANNEL_AUFSTELLUNG)
    if not kanal:
        return
    try:
        msg = await kanal.fetch_message(int(msg_id))
        mitglieder = await get_rolle_mitglieder(interaction.guild)
        datum = data.get("aktuelles_datum", get_morgen_datum())
        embed = build_embed(datum, mitglieder, data.get("eingefroren", False))
        await msg.edit(embed=embed)
    except Exception as e:
        print(f"Fehler beim Update der Nachricht: {e}")

# ─── NEUE ABSTIMMUNG POSTEN ───────────────────────────────────────────────────
async def neue_abstimmung_posten(guild):
    kanal = guild.get_channel(CHANNEL_AUFSTELLUNG)
    if not kanal:
        print("Aufstellungs-Channel nicht gefunden!")
        return

    datum = get_morgen_datum()
    data["abstimmung"]  = {}
    data["abmeldungen"] = {}
    data["eingefroren"] = False
    data["aktuelles_datum"] = datum

    mitglieder = await get_rolle_mitglieder(guild)
    embed = build_embed(datum, mitglieder, eingefroren=False)
    view  = AufstellungView()

    msg = await kanal.send(embed=embed, view=view)
    data["aktuelle_nachricht_id"] = str(msg.id)
    save_data(data)
    print(f"Neue Abstimmung gepostet für {datum}")

# ─── ABSTIMMUNG EINFRIEREN & ARCHIVIEREN ─────────────────────────────────────
async def abstimmung_einfrieren(guild):
    data["eingefroren"] = True
    save_data(data)

    # Aufstellungs-Channel: Nachricht updaten (eingefroren)
    kanal = guild.get_channel(CHANNEL_AUFSTELLUNG)
    msg_id = data.get("aktuelle_nachricht_id")
    mitglieder = await get_rolle_mitglieder(guild)
    datum = data.get("aktuelles_datum", get_heute_datum())

    if kanal and msg_id:
        try:
            msg = await kanal.fetch_message(int(msg_id))
            embed = build_embed(datum, mitglieder, eingefroren=True)
            await msg.edit(embed=embed, view=None)  # View entfernen = keine Buttons mehr
        except Exception as e:
            print(f"Fehler beim Einfrieren: {e}")

    # Archiv-Channel: Kopie senden
    archiv = guild.get_channel(CHANNEL_ARCHIV)
    if archiv:
        embed_archiv = build_embed(datum, mitglieder, eingefroren=True)
        embed_archiv.title = f"📁 ARCHIV – {embed_archiv.title}"
        await archiv.send(embed=embed_archiv)
        print(f"Abstimmung archiviert für {datum}")

# ─── TASKS ────────────────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def check_zeit():
    now = datetime.now(TIMEZONE)
    h, m = now.hour, now.minute

    # Jeden Tag 23:59 → neue Abstimmung für morgen
    if h == 23 and m == 59:
        for guild in bot.guilds:
            await neue_abstimmung_posten(guild)
        await asyncio.sleep(61)

    # Jeden Tag 20:25 → einfrieren + archivieren
    if h == 20 and m == 30 and not data.get("eingefroren", False):
        for guild in bot.guilds:
            await abstimmung_einfrieren(guild)
        await asyncio.sleep(61)

# ─── SLASH COMMANDS ───────────────────────────────────────────────────────────

# /setrolle – Rolle für Abstimmung setzen
@tree.command(name="setrolle", description="Setzt die Rolle die an der Aufstellung teilnimmt")
@app_commands.describe(rolle="Die Rolle die abgestimmt werden soll")
@app_commands.checks.has_permissions(administrator=True)
async def setrolle(interaction: discord.Interaction, rolle: discord.Role):
    data["rolle_id"] = str(rolle.id)
    save_data(data)
    await interaction.response.send_message(
        f"✅ Rolle **{rolle.name}** wurde gesetzt. Ab jetzt nehmen alle Mitglieder mit dieser Rolle an der Abstimmung teil.",
        ephemeral=True
    )

# /abmelden – Abmeldung für Aufstellung
@tree.command(name="abmelden", description="Melde dich von der Aufstellung ab")
@app_commands.describe(
    von="Von wann bist du abgemeldet? (z.B. 14.07.2025)",
    bis="Bis wann bist du abgemeldet? (z.B. 16.07.2025)",
    grund="Grund für die Abmeldung (intern, wird nicht angezeigt)"
)
async def abmelden(interaction: discord.Interaction, von: str, bis: str, grund: str):
    rolle_id = data.get("rolle_id")
    if rolle_id:
        rolle = interaction.guild.get_role(int(rolle_id))
        if rolle and rolle not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ Du hast keine Berechtigung zur Abmeldung (falsche Rolle).", ephemeral=True
            )
            return

    uid = str(interaction.user.id)
    data["abmeldungen"][uid] = {
        "von": von,
        "bis": bis,
        "grund": grund
    }
    # Aus Abstimmung entfernen
    data["abstimmung"].pop(uid, None)
    save_data(data)

    # Abstimmungs-Nachricht updaten
    kanal = interaction.guild.get_channel(CHANNEL_AUFSTELLUNG)
    msg_id = data.get("aktuelle_nachricht_id")
    if kanal and msg_id and not data.get("eingefroren"):
        try:
            msg = await kanal.fetch_message(int(msg_id))
            mitglieder = await get_rolle_mitglieder(interaction.guild)
            datum = data.get("aktuelles_datum", get_morgen_datum())
            embed = build_embed(datum, mitglieder)
            await msg.edit(embed=embed)
        except Exception as e:
            print(f"Fehler beim Update nach Abmeldung: {e}")

    # Bestätigung an Nutzer
    await interaction.response.send_message(
        f"✅ Abmeldung eingetragen!\n"
        f"📅 Von: **{von}**\n"
        f"📅 Bis: **{bis}**\n"
        f"Du wirst in der Aufstellung als 🏖️ Abgemeldet angezeigt.",
        ephemeral=True
    )

    # Info in Abmeldungs-Channel senden
    abm_kanal = interaction.guild.get_channel(CHANNEL_ABMELDUNG)
    if abm_kanal:
        embed_abm = discord.Embed(
            title="🏖️ Neue Abmeldung",
            color=EMBED_COLOR
        )
        embed_abm.add_field(name="Mitglied", value=interaction.user.mention, inline=True)
        embed_abm.add_field(name="Von", value=von, inline=True)
        embed_abm.add_field(name="Bis", value=bis, inline=True)
        embed_abm.set_footer(text="Narco City RP · Orga Management")
        embed_abm.timestamp = datetime.now(TIMEZONE)
        await abm_kanal.send(embed=embed_abm)

# /abstimmung – Manuelle neue Abstimmung (Admin)
@tree.command(name="abstimmung", description="Postet manuell eine neue Aufstellungs-Abstimmung")
@app_commands.checks.has_permissions(administrator=True)
async def abstimmung_manuell(interaction: discord.Interaction):
    await interaction.response.send_message("⏳ Erstelle neue Abstimmung...", ephemeral=True)
    await neue_abstimmung_posten(interaction.guild)
    await interaction.edit_original_response(content="✅ Neue Abstimmung wurde gepostet!")

# /status – Aktuellen Stand anzeigen (nur für Admins)
@tree.command(name="status", description="Zeigt den aktuellen Abstimmungsstand")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    mitglieder = await get_rolle_mitglieder(interaction.guild)
    datum = data.get("aktuelles_datum", get_morgen_datum())
    embed = build_embed(datum, mitglieder, data.get("eingefroren", False))
    await interaction.response.send_message(embed=embed, ephemeral=True)

# /abmeldung_loeschen – Abmeldung eines Mitglieds aufheben (Admin)
@tree.command(name="abmeldung_loeschen", description="Entfernt die Abmeldung eines Mitglieds")
@app_commands.describe(mitglied="Das Mitglied dessen Abmeldung entfernt werden soll")
@app_commands.checks.has_permissions(administrator=True)
async def abmeldung_loeschen(interaction: discord.Interaction, mitglied: discord.Member):
    uid = str(mitglied.id)
    if uid in data["abmeldungen"]:
        del data["abmeldungen"][uid]
        save_data(data)
        await interaction.response.send_message(
            f"✅ Abmeldung von **{mitglied.display_name}** wurde entfernt.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ **{mitglied.display_name}** hat keine aktive Abmeldung.", ephemeral=True
        )

# ─── BOT EVENTS ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")
    await tree.sync()
    bot.add_view(AufstellungView())  # Persistente View registrieren
    check_zeit.start()
    print("Tasks gestartet. Bot ist bereit!")

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung für diesen Befehl.", ephemeral=True
        )
    else:
        print(f"Command Error: {error}")
        await interaction.response.send_message(
            "❌ Ein Fehler ist aufgetreten.", ephemeral=True
        )

# ─── START ────────────────────────────────────────────────────────────────────
bot.run(TOKEN)
