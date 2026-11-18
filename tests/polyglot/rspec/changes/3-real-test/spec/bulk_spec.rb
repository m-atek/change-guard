require_relative "../lib/shop/pricing"

RSpec.describe "bulk discount" do
  it "leaves a small order at full price" do
    expect(Shop::Pricing.total(250, 2)).to eq(500)
  end

  it "gives ten items 10% off" do
    expect(Shop::Pricing.total(1000, 10)).to eq(9000)
  end
end
