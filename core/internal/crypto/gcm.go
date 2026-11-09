// Package crypto provides AES-256-GCM helpers for credentials and module tokens (core-03 §7).
package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
)

var (
	ErrDecrypt = errors.New("ciphertext authentication failed")
	ErrKeyLen  = errors.New("AES-256 key must be 32 bytes")
)

// Seal encrypts plaintext with a random 12-byte nonce. AAD binds the ciphertext to context
// (credential ref / module id and key version) so a row copied elsewhere fails to open.
func Seal(key, plaintext, aad []byte) (nonce, ciphertext []byte, err error) {
	if len(key) != 32 {
		return nil, nil, ErrKeyLen
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, nil, err
	}
	nonce = make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, nil, err
	}
	return nonce, gcm.Seal(nil, nonce, plaintext, aad), nil
}

// Open decrypts and authenticates. Tampered ciphertext, wrong key or wrong AAD → ErrDecrypt.
func Open(key, nonce, ciphertext, aad []byte) ([]byte, error) {
	if len(key) != 32 {
		return nil, ErrKeyLen
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	pt, err := gcm.Open(nil, nonce, ciphertext, aad)
	if err != nil {
		return nil, fmt.Errorf("%w", ErrDecrypt)
	}
	return pt, nil
}

// AADRef builds AAD = ref || key_version (big-endian uint32) as required by core-03 §3.17.
func AADRef(ref string, keyVersion int) []byte {
	buf := make([]byte, len(ref)+4)
	copy(buf, ref)
	binary.BigEndian.PutUint32(buf[len(ref):], uint32(keyVersion))
	return buf
}
