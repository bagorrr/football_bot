ALTER TABLE football_runtime.application_proposition_identities
    ADD COLUMN proposition_discriminator text;

UPDATE football_runtime.application_proposition_identities
SET proposition_discriminator = opportunity_id
WHERE proposition_discriminator IS NULL;

ALTER TABLE football_runtime.application_proposition_identities
    ALTER COLUMN proposition_discriminator SET NOT NULL,
    ADD CONSTRAINT application_proposition_identities_discriminator_nonempty
        CHECK (proposition_discriminator <> ''),
    ADD CONSTRAINT application_proposition_identities_source_discriminator_key
        UNIQUE (source_message_id, proposition_discriminator);

GRANT UPDATE (proposition_discriminator)
    ON football_runtime.application_proposition_identities
    TO football_application;
