-- ════════════════════════════════════════════════════════════════
--  Медицинская клиника — схема базы данных Supabase
--  Запустите этот SQL в разделе: Supabase → SQL Editor → New Query
-- ════════════════════════════════════════════════════════════════

-- Включаем расширение для UUID
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── Пациенты ────────────────────────────────────────────────
CREATE TABLE patients (
    id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    phone       VARCHAR(20) UNIQUE NOT NULL,
    full_name   VARCHAR(255),
    birth_date  DATE,
    language    VARCHAR(5)  DEFAULT 'ru',  -- 'ru' или 'kz'
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Врачи ───────────────────────────────────────────────────
CREATE TABLE doctors (
    id               UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    full_name        VARCHAR(255) NOT NULL,
    specialization   VARCHAR(100) NOT NULL,  -- therapist, surgeon, cardiologist ...
    specialization_ru VARCHAR(100),          -- «Терапевт»
    specialization_kz VARCHAR(100),          -- «Терапевт»
    phone            VARCHAR(20),
    is_active        BOOLEAN     DEFAULT TRUE,
    work_start       TIME        DEFAULT '09:00',
    work_end         TIME        DEFAULT '18:00',
    slot_minutes     INT         DEFAULT 30,  -- длина приёма в минутах
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Записи на приём ────────────────────────────────────────
CREATE TABLE appointments (
    id                  UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    patient_id          UUID        REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id           UUID        REFERENCES doctors(id)  ON DELETE CASCADE,
    appointment_datetime TIMESTAMPTZ NOT NULL,
    status              VARCHAR(20) DEFAULT 'scheduled',
        -- scheduled | confirmed | cancelled | completed
    reminder_sent       BOOLEAN     DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Сессии звонков ─────────────────────────────────────────
CREATE TABLE call_sessions (
    id           UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    call_id      VARCHAR(255) UNIQUE NOT NULL,
    phone        VARCHAR(20)  NOT NULL,
    patient_id   UUID         REFERENCES patients(id) ON DELETE SET NULL,
    state        VARCHAR(50)  DEFAULT 'greeting',
    language     VARCHAR(5)   DEFAULT 'ru',
    context      JSONB        DEFAULT '{}',
    started_at   TIMESTAMPTZ  DEFAULT NOW(),
    ended_at     TIMESTAMPTZ,
    status       VARCHAR(20)  DEFAULT 'active'
        -- active | completed | transferred | failed
);

-- ─── Индексы ────────────────────────────────────────────────
CREATE INDEX idx_appointments_datetime   ON appointments(appointment_datetime);
CREATE INDEX idx_appointments_patient    ON appointments(patient_id);
CREATE INDEX idx_appointments_doctor     ON appointments(doctor_id);
CREATE INDEX idx_appointments_reminder   ON appointments(reminder_sent, status, appointment_datetime);
CREATE INDEX idx_call_sessions_call_id   ON call_sessions(call_id);
CREATE INDEX idx_patients_phone          ON patients(phone);

-- ─── Тригер: auto update updated_at ─────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_appointments_updated_at
    BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── Тестовые данные: врачи ───────────────────────────────────
INSERT INTO doctors (full_name, specialization, specialization_ru, specialization_kz, work_start, work_end) VALUES
('Алибеков Ержан Сейткалиевич',  'therapist',     'Терапевт',     'Терапевт',     '08:00', '17:00'),
('Мусина Айгерим Болатовна',      'therapist',     'Терапевт',     'Терапевт',     '12:00', '20:00'),
('Ковалёв Дмитрий Сергеевич',     'surgeon',       'Хирург',       'Хирург',       '09:00', '18:00'),
('Нурланова Гульнар Камаловна',   'cardiologist',  'Кардиолог',    'Кардиолог',    '09:00', '17:00'),
('Петров Андрей Владимирович',    'neurologist',   'Невролог',     'Невролог',     '10:00', '19:00'),
('Ахметова Жанна Рустемовна',     'pediatrician',  'Педиатр',      'Педиатр',      '08:00', '16:00'),
('Сейткали Динара Маратовна',     'gynecologist',  'Гинеколог',    'Гинеколог',    '09:00', '18:00'),
('Захаров Игорь Павлович',        'ophthalmologist','Офтальмолог',  'Офтальмолог',  '09:00', '17:00'),
('Байжанова Сауле Асхатовна',     'dermatologist', 'Дерматолог',   'Дерматолог',   '10:00', '18:00'),
('Омаров Бауыржан Ермекович',     'endocrinologist','Эндокринолог', 'Эндокринолог', '09:00', '17:00');

-- ─── Полезные VIEW ───────────────────────────────────────────

-- Свободные слоты врача на дату
CREATE OR REPLACE VIEW available_slots AS
SELECT
    d.id           AS doctor_id,
    d.full_name    AS doctor_name,
    d.specialization,
    d.specialization_ru,
    d.specialization_kz,
    d.work_start,
    d.work_end,
    d.slot_minutes
FROM doctors d
WHERE d.is_active = TRUE;

-- Завтрашние записи без напоминания
CREATE OR REPLACE VIEW tomorrow_reminders AS
SELECT
    a.id,
    a.appointment_datetime,
    p.phone,
    p.full_name    AS patient_name,
    p.language,
    d.full_name    AS doctor_name,
    d.specialization_ru,
    d.specialization_kz
FROM appointments a
JOIN patients p ON p.id = a.patient_id
JOIN doctors  d ON d.id = a.doctor_id
WHERE
    a.status        = 'scheduled'
    AND a.reminder_sent = FALSE
    AND a.appointment_datetime::date = (CURRENT_DATE + INTERVAL '1 day');
