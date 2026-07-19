# Inbetriebnahme-Checkliste (Rollout)

Diese Checkliste vor dem ersten echten Betrieb vollständig durcharbeiten.
Die Anlage schaltet eine echte Pumpe — jede Ebene der Absicherung zählt.

## A. Hardware-Verifikation

- [ ] **Typenschild der Pumpe** ablesen: Nennstrom, Motortyp,
      Anlaufkondensator? Bei extremem Anlaufstrom oder sehr häufigen
      Schaltzyklen ein Schütz zwischen Shelly und Pumpe setzen.
- [ ] **Shelly-Schutzfunktionen** konfigurieren (unabhängig vom Skript):
      Überleistungsgrenze (z. B. 1200 W bei 800-W-Pumpe), Überstrom,
      Übertemperatur-Abschaltung.
- [ ] **Geräte-Authentifizierung** am Shelly aktivieren, Passwort im Panel
      hinterlegen (niemals in Git!).
- [ ] **NTP & Zeitzone** am Shelly prüfen (Uhrzeit gültig? Zeitfenster und
      Filterlaufzeit hängen daran).
- [ ] Fühler beschriftet (W1, W2, M1, M2, A1) und im Panel der richtigen
      Rolle zugeordnet? **Wasser↔Matte vertauscht = invertierte Regelung!**
      Zum Test einen Fühler in warmes Wasser halten und die Anzeige
      beobachten.

## B. Bench-Test (Pumpe noch nicht angeschlossen / Dummy-Last)

- [ ] Beide Skripte laufen und starten automatisch (Neustart-Test).
- [ ] Watchdog-Test: `pool-control` manuell stoppen → nach ≤ 2 min wird es
      neu gestartet (Log prüfen).
- [ ] Konfigurationsänderung im Panel → wird innerhalb weniger Sekunden als
      „bestätigt“ angezeigt.
- [ ] Handbetrieb mit kurzem Zeitlimit → Relais schaltet und fällt nach
      Ablauf zurück.
- [ ] Simulierter Fühlerausfall (Fühler abziehen) → erwartete Störung +
      Benachrichtigung.

## C. Erste echte Läufe

- [ ] **Konservative Erstkonfiguration**: kurze Handbetrieb-Zeitlimits,
      alle Störungs-Strategien auf `safe_off`, Benachrichtigungen aktiv.
- [ ] **Pumpenkalibrierung** durchführen (Steuerung → Kalibrieren), Wert
      plausibel? (~ Nennleistung der Pumpe)
- [ ] Trockenlauferkennung testen, falls gefahrlos möglich: Ventil kurz
      schließen → Störung `dry_run` mit Sperre. Sonst auf das
      Kalibrierband vertrauen.
- [ ] **48 h Beobachtung** mit `safe_off`-Strategien, bevor irgendwo
      `fallback_schedule` aktiviert wird.
- [ ] Heizfenster, ΔT-Schwellen und Filterlaufzeit an die Anlage anpassen.

## D. Saisonbetrieb

- [ ] **Einwinterung**: Modus `winter` setzen, Kreislauf entleeren.
      Achtung: der Frostschutz ist im Wintermodus bewusst deaktiviert
      (entleerter Kreislauf — Pumpe darf nicht laufen).
- [ ] **Frühjahr**: Fühler-Plausibilität prüfen, Pumpenleistung neu
      kalibrieren, Zähler/Verlauf kontrollieren, Backup einrichten
      (System → Backups → geplant).

## E. Restrisiken (dokumentiert, akzeptiert)

- Taster wirkungslos, wenn das Skript vollständig tot ist (Inputs sind
  „detached“). Absicherung: Watchdog + Shelly-App als Fallback.
- Leistungssignatur erkennt keinen Schlauchbruch, bei dem die Pumpe weiter
  Wasser fördert. Hinweis-Warnung „hydraulische Plausibilität“ beachten.
- Nach Stagnationsphasen mit heißer Matte schwappt beim Anlauf kurz sehr
  warmes Wasser ins Becken — normal.
