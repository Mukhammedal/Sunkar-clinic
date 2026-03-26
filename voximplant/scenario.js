/**
 * VoxEngine сценарий — ВХОДЯЩИЕ звонки
 */

require(Modules.ASR);

var BACKEND_URL     = "https://med.rckazakstan.com";
var OPERATOR_NUMBER = "+77071234567";
var ASR_LANGUAGE    = ASRLanguage.RUSSIAN_RU;

var mainCall    = null;
var callId      = null;
var callerPhone = null;
var asrInstance = null;

VoxEngine.addEventListener(AppEvents.CallAlerting, function (e) {
    mainCall    = e.call;
    callId      = e.call.id();
    callerPhone = e.call.callerid();
    Logger.write("Incoming call from: " + callerPhone);
    mainCall.addEventListener(CallEvents.Connected, onCallConnected);
    mainCall.addEventListener(CallEvents.Disconnected, onCallDisconnected);
    mainCall.addEventListener(CallEvents.Failed, function (ev) {
        endSession("failed");
        VoxEngine.terminate();
    });
    mainCall.answer();
});

function onCallConnected(e) {
    Logger.write("Call connected.");
    mainCall.say("Добро пожаловать в клинику. Скажите русский или казахский.", { language: VoiceList.Russian_Female_Ekaterina });
    mainCall.addEventListener(CallEvents.PlaybackFinished, function onGreeting() {
        mainCall.removeEventListener(CallEvents.PlaybackFinished, onGreeting);
        startListening("language_select");
    });
}

function onCallDisconnected(e) {
    Logger.write("Call disconnected.");
    endSession("completed");
    VoxEngine.terminate();
}

function processConversation(state, userText) {
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
                Logger.write("Backend error: " + result.code);
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
            Logger.write("action=" + response.action + " state=" + response.state);

            switch (response.action) {
                case "transfer":
                    transferToOperator(OPERATOR_NUMBER);
                    break;
                case "hangup":
                    sayText(response.text, function () { mainCall.hangup(); });
                    break;
                default:
                    sayText(response.text, function () { startListening(response.state); });
                    break;
            }
        }
    );
}

function sayText(text, onFinished) {
    mainCall.say(text, { language: VoiceList.Russian_Female_Ekaterina });
    var handler = function () {
        mainCall.removeEventListener(CallEvents.PlaybackFinished, handler);
        if (onFinished) onFinished();
    };
    mainCall.addEventListener(CallEvents.PlaybackFinished, handler);
}

function startListening(returnState) {
    if (asrInstance) {
        try { mainCall.stopMediaTo(asrInstance); } catch (e) {}
    }
    asrInstance = VoxEngine.createASR({
        lang: ASR_LANGUAGE,
        singleUtterance: true,
        noSpeechTimeout: 7,
        maxSpeechTimeout: 20
    });
    asrInstance.addEventListener(ASREvents.Result, function (e) {
        Logger.write("ASR: [" + e.text + "] conf=" + e.confidence);
        mainCall.stopMediaTo(asrInstance);
        asrInstance = null;
        processConversation(returnState, (e.confidence > 0.3) ? e.text : "");
    });
    asrInstance.addEventListener(ASREvents.NoSpeech, function () {
        mainCall.stopMediaTo(asrInstance);
        asrInstance = null;
        processConversation(returnState, "");
    });
    asrInstance.addEventListener(ASREvents.Error, function (e) {
        mainCall.stopMediaTo(asrInstance);
        asrInstance = null;
        processConversation(returnState, "");
    });
    mainCall.sendMediaTo(asrInstance);
}

function transferToOperator(operatorNumber) {
    var operatorCall = VoxEngine.callPSTN(operatorNumber, callerPhone);
    operatorCall.addEventListener(CallEvents.Connected, function () {
        VoxEngine.sendMediaBetween(mainCall, operatorCall);
    });
    operatorCall.addEventListener(CallEvents.Disconnected, function () {
        mainCall.hangup();
        VoxEngine.terminate();
    });
    operatorCall.addEventListener(CallEvents.Failed, function (e) {
        mainCall.say("Оператор недоступен. Перезвоните позже.", { language: VoiceList.Russian_Female_Ekaterina });
        mainCall.addEventListener(CallEvents.PlaybackFinished, function () { mainCall.hangup(); });
    });
}

function playFallbackAndHangup() {
    mainCall.say("Техническая ошибка. Перезвоните позже.", { language: VoiceList.Russian_Female_Ekaterina });
    mainCall.addEventListener(CallEvents.PlaybackFinished, function () { mainCall.hangup(); });
}

function endSession(status) {
    if (!callId) return;
    Net.httpRequestAsync(
        BACKEND_URL + "/api/call/end",
        {
            method:   "POST",
            headers:  { "Content-Type": "application/json" },
            postData: JSON.stringify({ call_id: callId, status: status })
        },
        function (result) { Logger.write("Session ended: " + result.code); }
    );
}
