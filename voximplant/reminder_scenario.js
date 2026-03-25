/**
 * VoxEngine сценарий — ИСХОДЯЩИЕ звонки-напоминания
 *
 * Загрузите в Voximplant Dashboard как отдельный сценарий.
 * Создайте отдельное Rule для исходящих звонков (Outbound).
 * ID этого Rule → VOXIMPLANT_RULE_ID в .env
 *
 * Python-бэкенд запускает сценарий через:
 *   POST https://api.voximplant.com/platform_api/StartScenarios/
 *   с полем script_custom_data = JSON с данными пациента
 */

var BACKEND_URL = "https://med.rckazakstan.com";

var customData  = {};
var reminderCall = null;

// ── Старт сценария ────────────────────────────────────────────────────────────
VoxEngine.addEventListener(AppEvents.Started, function () {
    // Получаем данные, переданные из Python
    try {
        customData = JSON.parse(VoxEngine.customData());
    } catch (e) {
        Logger.write("Failed to parse customData: " + e);
        VoxEngine.terminate();
        return;
    }

    Logger.write("Reminder scenario started for: " + customData.to_number);

    // Звоним пациенту
    reminderCall = VoxEngine.callPSTN(customData.to_number, customData.caller_id || "");

    reminderCall.addEventListener(CallEvents.Connected, onReminderConnected);
    reminderCall.addEventListener(CallEvents.Disconnected, onReminderDisconnected);
    reminderCall.addEventListener(CallEvents.Failed, function (e) {
        Logger.write("Reminder call failed: " + e.reason);
        VoxEngine.terminate();
    });
});

// ── Пациент ответил ───────────────────────────────────────────────────────────
function onReminderConnected(e) {
    Logger.write("Patient answered: " + customData.to_number);

    // Получить аудио-напоминание с бэкенда
    Net.httpRequestAsync(
        BACKEND_URL + "/api/call/process",
        {
            method:   "POST",
            headers:  { "Content-Type": "application/json" },
            postData: JSON.stringify({
                call_id:   VoxEngine.callId(),
                phone:     customData.to_number,
                state:     "reminder",
                user_text: JSON.stringify(customData)   // Передаём все данные
            })
        },
        function (result) {
            if (result.code !== 200) {
                Logger.write("Backend error: " + result.code);
                playFallback();
                return;
            }

            var response = JSON.parse(result.text);
            playReminderAudio(response.audio_url);
        }
    );
}

function playReminderAudio(audioUrl) {
    var player = VoxEngine.createURLPlayer(audioUrl);

    player.addEventListener(PlayerEvents.PlaybackFinished, function () {
        Logger.write("Reminder message played");
        reminderCall.hangup();
    });

    player.addEventListener(PlayerEvents.PlaybackError, function (e) {
        Logger.write("Playback error: " + e.error);
        reminderCall.hangup();
    });

    reminderCall.startPlayback(player);
}

function playFallback() {
    reminderCall.say(
        "Здравствуйте! Звоним из медицинской клиники для напоминания о вашей записи на завтра. " +
        "Пожалуйста, не забудьте прийти вовремя. Спасибо!",
        { language: VoiceList.Russian_Female_Ekaterina }
    );
    reminderCall.addEventListener(CallEvents.PlaybackFinished, function () {
        reminderCall.hangup();
    });
}

function onReminderDisconnected(e) {
    Logger.write("Reminder call disconnected");
    VoxEngine.terminate();
}
