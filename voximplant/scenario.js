/**
 * VoxEngine сценарий — ВХОДЯЩИЕ звонки
 *
 * Загрузите этот файл в Voximplant Dashboard:
 *   Applications → Your App → Scenarios → New Scenario
 *
 * Затем создайте Rule (Routing → Rules):
 *   - Pattern: .* (все входящие)
 *   - Scenario: этот файл
 */

require(Modules.ASR);

// ── Настройки ─────────────────────────────────────────────────────────────────
var BACKEND_URL     = "https://hornblendic-harper-unuseable.ngrok-free.dev";
var OPERATOR_NUMBER = "+77071234567";               // ← номер живого оператора
var ASR_LANGUAGE    = ASRLanguage.RUSSIAN_RU;       // Язык распознавания речи

var mainCall   = null;
var callId     = null;
var callerPhone = null;
var currentState = "start";
var asrInstance  = null;

// ── Входящий звонок ──────────────────────────────────────────────────────────
VoxEngine.addEventListener(AppEvents.CallAlerting, function (e) {
    mainCall    = e.call;
    callId      = VoxEngine.callId();
    callerPhone = e.call.callerid();

    Logger.write("Incoming call from: " + callerPhone + " | callId: " + callId);

    mainCall.addEventListener(CallEvents.Connected, onCallConnected);
    mainCall.addEventListener(CallEvents.Disconnected, onCallDisconnected);
    mainCall.addEventListener(CallEvents.Failed, function (e) {
        Logger.write("Call failed: " + e.reason);
        endSession("failed");
        VoxEngine.terminate();
    });

    mainCall.answer();
});

// ── Звонок принят ─────────────────────────────────────────────────────────────
function onCallConnected(e) {
    Logger.write("Call connected. Starting conversation.");
    processConversation("start", "");
}

// ── Звонок завершён ───────────────────────────────────────────────────────────
function onCallDisconnected(e) {
    Logger.write("Call disconnected.");
    endSession("completed");
    VoxEngine.terminate();
}

// ── Основной цикл разговора ───────────────────────────────────────────────────
function processConversation(state, userText) {
    currentState = state;

    Net.httpRequestAsync(
        BACKEND_URL + "/api/call/process",
        {
            method:   "POST",
            headers:  { "Content-Type": "application/json" },
            postData: JSON.stringify({
                call_id:   callId,
                phone:     callerPhone,
                state:     state,
                user_text: userText
            })
        },
        function (result) {
            if (result.code !== 200) {
                Logger.write("Backend error HTTP " + result.code + ": " + result.text);
                playFallbackAndHangup();
                return;
            }

            var response;
            try {
                response = JSON.parse(result.text);
            } catch (err) {
                Logger.write("JSON parse error: " + err);
                playFallbackAndHangup();
                return;
            }

            Logger.write(
                "Backend response: action=" + response.action +
                " state=" + response.state
            );

            currentState = response.state;

            switch (response.action) {
                case "transfer":
                    transferToOperator(response.operator_number || OPERATOR_NUMBER);
                    break;
                case "hangup":
                    playAudio(response.audio_url, function () {
                        mainCall.hangup();
                    });
                    break;
                default: // "play"
                    playAudio(response.audio_url, function () {
                        startListening(response.state);
                    });
                    break;
            }
        }
    );
}

// ── Воспроизведение аудио ─────────────────────────────────────────────────────
function playAudio(audioUrl, onFinished) {
    var player = VoxEngine.createURLPlayer(audioUrl);

    player.addEventListener(PlayerEvents.PlaybackFinished, function () {
        Logger.write("Playback finished: " + audioUrl);
        if (onFinished) onFinished();
    });

    player.addEventListener(PlayerEvents.PlaybackError, function (e) {
        Logger.write("Playback error: " + e.error + " URL=" + audioUrl);
        if (onFinished) onFinished();
    });

    mainCall.startPlayback(player);
}

// ── Распознавание речи ────────────────────────────────────────────────────────
function startListening(returnState) {
    // Останавливаем предыдущий ASR
    if (asrInstance) {
        try { mainCall.stopMediaTo(asrInstance); } catch (e) {}
    }

    asrInstance = VoxEngine.createASR({
        lang:             ASR_LANGUAGE,
        singleUtterance:  true,
        noSpeechTimeout:  7,    // секунд тишины до завершения
        maxSpeechTimeout: 20    // максимум ждём речи
    });

    asrInstance.addEventListener(ASREvents.Result, function (e) {
        Logger.write("ASR result: [" + e.text + "] confidence=" + e.confidence);
        mainCall.stopMediaTo(asrInstance);
        asrInstance = null;

        var recognized = (e.confidence > 0.3) ? e.text : "";
        processConversation(returnState, recognized);
    });

    asrInstance.addEventListener(ASREvents.NoSpeech, function () {
        Logger.write("ASR: no speech detected");
        mainCall.stopMediaTo(asrInstance);
        asrInstance = null;
        processConversation(returnState, "");
    });

    asrInstance.addEventListener(ASREvents.Error, function (e) {
        Logger.write("ASR error: " + e.error);
        mainCall.stopMediaTo(asrInstance);
        asrInstance = null;
        processConversation(returnState, "");
    });

    mainCall.sendMediaTo(asrInstance);
}

// ── Перевод на оператора ──────────────────────────────────────────────────────
function transferToOperator(operatorNumber) {
    Logger.write("Transferring to operator: " + operatorNumber);

    var operatorCall = VoxEngine.callPSTN(operatorNumber, callerPhone);

    operatorCall.addEventListener(CallEvents.Connected, function () {
        Logger.write("Operator connected");
        VoxEngine.sendMediaBetween(mainCall, operatorCall);
    });

    operatorCall.addEventListener(CallEvents.Disconnected, function () {
        Logger.write("Operator disconnected");
        mainCall.hangup();
        VoxEngine.terminate();
    });

    operatorCall.addEventListener(CallEvents.Failed, function (e) {
        Logger.write("Operator call failed: " + e.reason);
        // Оператор недоступен — попрощаться с пациентом
        mainCall.say(
            "К сожалению, оператор сейчас недоступен. Пожалуйста, перезвоните позже.",
            { language: VoiceList.Russian_Female_Ekaterina }
        );
        mainCall.addEventListener(CallEvents.PlaybackFinished, function () {
            mainCall.hangup();
        });
    });
}

// ── Заглушка при ошибке ───────────────────────────────────────────────────────
function playFallbackAndHangup() {
    mainCall.say(
        "Произошла техническая ошибка. Пожалуйста, перезвоните позже.",
        { language: VoiceList.Russian_Female_Ekaterina }
    );
    mainCall.addEventListener(CallEvents.PlaybackFinished, function () {
        mainCall.hangup();
    });
}

// ── Завершение сессии на бэкенде ──────────────────────────────────────────────
function endSession(status) {
    if (!callId) return;
    Net.httpRequestAsync(
        BACKEND_URL + "/api/call/end",
        {
            method:   "POST",
            headers:  { "Content-Type": "application/json" },
            postData: JSON.stringify({ call_id: callId, status: status })
        },
        function (result) {
            Logger.write("Session ended, backend status: " + result.code);
        }
    );
}
