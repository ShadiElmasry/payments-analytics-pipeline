from payments.spark_clean import private_key_body


def test_private_key_is_flattened_for_the_spark_connector(tmp_path):
    key_file = tmp_path / "key.p8"
    key_file.write_text("-----BEGIN PRIVATE KEY-----\nAAAA\nBBBB\n-----END PRIVATE KEY-----\n")
    assert private_key_body(str(key_file)) == "AAAABBBB"   # one line, no header or footer
