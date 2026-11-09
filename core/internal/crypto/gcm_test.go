package crypto

import (
	"bytes"
	"testing"
)

func TestSealOpenRoundTrip(t *testing.T) {
	key := bytes.Repeat([]byte{0x11}, 32)
	aad := AADRef("cred:test", 1)
	n, c, err := Seal(key, []byte("super-secret"), aad)
	if err != nil {
		t.Fatal(err)
	}
	pt, err := Open(key, n, c, aad)
	if err != nil || string(pt) != "super-secret" {
		t.Fatalf("got %q err=%v", pt, err)
	}
}

func TestTamperAndWrongAADAndKey(t *testing.T) {
	key := bytes.Repeat([]byte{0x22}, 32)
	aad := AADRef("cred:test", 1)
	n, c, _ := Seal(key, []byte("secret-value"), aad)
	c[0] ^= 0xff
	if _, err := Open(key, n, c, aad); err == nil {
		t.Fatal("tampered ciphertext opened")
	}
	n, c, _ = Seal(key, []byte("secret-value"), aad)
	if _, err := Open(key, n, c, AADRef("cred:other", 1)); err == nil {
		t.Fatal("wrong AAD opened")
	}
	other := bytes.Repeat([]byte{0x33}, 32)
	if _, err := Open(other, n, c, aad); err == nil {
		t.Fatal("wrong key opened")
	}
}
