-- Phase 21.7 rollback: drop all enrichment tables in reverse dependency order

DROP TABLE IF EXISTS pitch_conditions CASCADE;
DROP TABLE IF EXISTS weather_actuals CASCADE;
DROP TABLE IF EXISTS weather_forecasts CASCADE;
DROP TABLE IF EXISTS referee_profiles CASCADE;
DROP TABLE IF EXISTS referee_assignments CASCADE;
DROP TABLE IF EXISTS availability CASCADE;
DROP TABLE IF EXISTS injuries CASCADE;
DROP TABLE IF EXISTS suspensions CASCADE;
DROP TABLE IF EXISTS contracts CASCADE;
DROP TABLE IF EXISTS transfers CASCADE;
